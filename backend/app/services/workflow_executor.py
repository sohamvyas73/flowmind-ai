import logging
import re
import time
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import httpx
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Logging helpers ────────────────────────────────────────────────────────────

_MAX_LOG_STR = 200  # max chars for any plain string in logs


def _sanitize_str(s: str) -> str:
    """Replace base64 data URIs; truncate other long strings."""
    if s.startswith("data:"):
        mime = s.split(";")[0].replace("data:", "")
        size_kb = round(len(s) * 0.75 / 1024)
        return f"[file: {mime}, ~{size_kb} KB]"
    if len(s) > _MAX_LOG_STR:
        return f"{s[:_MAX_LOG_STR]}… [{len(s)} chars]"
    return s


def _safe_value(v: Any) -> Any:
    """Recursively sanitize any value for logging."""
    if isinstance(v, str):
        return _sanitize_str(v)
    if isinstance(v, dict):
        return {k: _safe_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_safe_value(item) for item in v]
    return v


def _safe_result(result: Any) -> Any:
    return _safe_value(result)


def _strip_binaries(value: Any) -> Any:
    """Remove base64 data URIs from a value tree but keep all other content intact.
    Used to pass full LLM outputs to downstream nodes without flooding the context."""
    if isinstance(value, str):
        if value.startswith("data:"):
            mime = value.split(";")[0].replace("data:", "")
            return f"[file: {mime}]"
        return value
    if isinstance(value, dict):
        return {k: _strip_binaries(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_binaries(item) for item in value]
    return value


def _safe_messages(messages: list) -> list:
    """Sanitize LLM message list for logging."""
    safe = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, list):
                safe_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            mime = url.split(";")[0].replace("data:", "")
                            safe_parts.append({"type": "image_url", "mime": mime, "size_kb": round(len(url) * 0.75 / 1024)})
                        else:
                            safe_parts.append(part)
                    elif isinstance(part, dict) and part.get("type") == "media":
                        data = part.get("data", "")
                        safe_parts.append({"type": "media", "mime_type": part.get("mime_type"), "size_kb": round(len(data) * 0.75 / 1024)})
                    elif isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "")
                        safe_parts.append({"type": "text", "text": _sanitize_str(text)})
                    else:
                        safe_parts.append(_safe_value(part))
                safe.append({"role": "human", "content": safe_parts})
            else:
                safe.append({"role": "human", "content": _sanitize_str(str(content))})
        elif isinstance(msg, tuple):
            role, content = msg
            safe.append({"role": role, "content": _sanitize_str(str(content))})
        else:
            safe.append(_sanitize_str(str(msg)))
    return safe


# ── Node executor ──────────────────────────────────────────────────────────────

class NodeExecutor:

    def __init__(self):
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set — AI nodes will return errors")

    def _get_llm(self, temperature: float = 0.0) -> Optional[ChatGoogleGenerativeAI]:
        """Create an LLM instance from current settings on every call.
        This means changing GEMINI_MODEL or GEMINI_API_KEY in .env and
        running `docker compose restart backend` is all that's needed."""
        if not settings.GEMINI_API_KEY:
            return None
        logger.info("LLM ready: model=%s temperature=%.2f", settings.GEMINI_MODEL, temperature)
        return ChatGoogleGenerativeAI(
            google_api_key=settings.GEMINI_API_KEY,
            model=settings.GEMINI_MODEL,
            temperature=temperature,
            convert_system_message_to_human=True,
        )

    # ── Input node ─────────────────────────────────────────────────────────────

    async def execute_input_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id = context.get("current_node_id", "")
        raw_input = context.get("input") or {}
        fields_def: List[Dict[str, str]] = node_data.get("fields", [])

        if not fields_def:
            fields_def = [{"id": "default", "name": "input", "type": node_data.get("inputType", "text")}]

        logger.info(
            "[input_node] node=%s | expected_fields=%s",
            node_id,
            [f["name"] for f in fields_def],
        )

        inputs: Dict[str, Any] = {}
        filenames: Dict[str, str] = {}

        live = raw_input.get("node_inputs", {}).get(node_id)
        if live:
            logger.info("[input_node] node=%s | source=execution_modal | keys=%s", node_id, list(live.keys()))
            for field in fields_def:
                name = field["name"]
                val = live.get(name)
                if isinstance(val, dict):
                    content = val.get("content", "")
                    inputs[name] = content
                    if val.get("filename"):
                        filenames[name] = val["filename"]
                        logger.info(
                            "[input_node] node=%s | field=%s | type=file | filename=%s | size_chars=%d",
                            node_id, name, val["filename"], len(content),
                        )
                    else:
                        logger.info(
                            "[input_node] node=%s | field=%s | type=text | preview=%r",
                            node_id, name, content[:100],
                        )
                elif val is not None:
                    inputs[name] = str(val)
                    logger.info("[input_node] node=%s | field=%s | value=%r", node_id, name, str(val)[:100])

            result = {"inputs": inputs, "filenames": filenames, "timestamp": datetime.utcnow().isoformat()}
            logger.info("[input_node] node=%s | result_fields=%s", node_id, list(inputs.keys()))
            return result

        if raw_input and "node_inputs" not in raw_input:
            logger.info("[input_node] node=%s | source=trigger_api | body_keys=%s", node_id, list(raw_input.keys()))
            for field in fields_def:
                name = field["name"]
                if name in raw_input:
                    inputs[name] = raw_input[name]
                    logger.info("[input_node] node=%s | field=%s | found=true", node_id, name)
                else:
                    logger.info("[input_node] node=%s | field=%s | found=false (not in body)", node_id, name)

            result = {"inputs": inputs, "filenames": filenames, "timestamp": datetime.utcnow().isoformat()}
            return result

        logger.info("[input_node] node=%s | source=none | returning empty inputs", node_id)
        return {"inputs": inputs, "filenames": filenames, "timestamp": datetime.utcnow().isoformat()}

    # ── AI node ────────────────────────────────────────────────────────────────

    async def execute_ai_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id = context.get("current_node_id", "")
        temperature = float(node_data.get("temperature", 0.7))
        output_format = node_data.get("outputFormat", "text")
        output_schema = node_data.get("outputSchema", "")
        llm = self._get_llm(temperature=temperature)

        if not llm:
            logger.error("[ai_node] node=%s | error=LLM not configured", node_id)
            return {"error": "AI service not configured"}

        ai_task = node_data.get("aiTask", "reasoning")
        prompt = node_data.get("prompt", "")
        input_data = context.get("previous_output", {})

        logger.info("[ai_node] node=%s | task=%s | format=%s | prompt=%r", node_id, ai_task, output_format, prompt[:200])

        system_prompt = self._get_system_prompt(ai_task)
        format_instructions: Dict[str, str] = {
            "json":          "\n\nYou MUST respond with ONLY valid JSON — no markdown fences, no explanation.",
            "markdown":      "\n\nFormat your response as clean Markdown.",
            "csv":           "\n\nReturn your response as CSV (comma-separated values) with a header row on the first line. No other text.",
            "html":          "\n\nFormat your response as clean HTML (content elements only, no doctype or <html> wrapper).",
            "table":         "\n\nPresent your findings as a Markdown table with clearly labeled column headers.",
            "bullet_list":   "\n\nRespond using a concise bullet-point list. Prefix each item with '- '.",
            "custom_schema": f"\n\nYou MUST respond with ONLY valid JSON matching this exact schema:\n{output_schema}\nNo markdown fences, no extra text — pure JSON only.",
        }
        if output_format in format_instructions:
            system_prompt += format_instructions[output_format]
        messages = self._build_messages(system_prompt, prompt, input_data)

        logger.info(
            "[ai_node] node=%s | MODEL INPUT ↓\n%s",
            node_id,
            json.dumps(_safe_messages(messages), indent=2, ensure_ascii=False),
        )

        t0 = time.time()
        try:
            response = await asyncio.to_thread(llm.invoke, messages)
            elapsed = time.time() - t0

            logger.info(
                "[ai_node] node=%s | MODEL OUTPUT ↓ (%.2fs)\n%s",
                node_id,
                elapsed,
                response.content,
            )

            result_value: Any = response.content
            if output_format in ("json", "custom_schema"):
                raw = response.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                try:
                    result_value = json.loads(raw)
                except json.JSONDecodeError:
                    pass  # keep as text if JSON parse fails

            result = {
                "task": ai_task,
                "result": result_value,
                "format": output_format,
                "confidence": 0.85,
                "timestamp": datetime.utcnow().isoformat(),
            }
            return result

        except Exception as e:
            logger.error("[ai_node] node=%s | LLM call failed: %s", node_id, e, exc_info=True)
            return {"error": str(e)}

    # ── Verification node ──────────────────────────────────────────────────────

    async def execute_verification_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id = context.get("current_node_id", "")
        llm = self._get_llm()

        if not llm:
            logger.error("[verification_node] node=%s | error=LLM not configured", node_id)
            return {"error": "AI service not configured"}

        verification_type = node_data.get("verificationType", "consistency")
        input_data = context.get("previous_output", {})

        logger.info("[verification_node] node=%s | type=%s", node_id, verification_type)

        system_prompt = (
            f"You are a verification agent. Perform {verification_type} verification. "
            "Provide: 1) result (pass/fail), 2) confidence score (0-1), "
            "3) issues found, 4) recommendations."
        )
        user_prompt = f"Verify the following data for {verification_type}:"
        messages = self._build_messages(system_prompt, user_prompt, input_data)

        logger.info(
            "[verification_node] node=%s | MODEL INPUT ↓\n%s",
            node_id,
            json.dumps(_safe_messages(messages), indent=2, ensure_ascii=False),
        )

        t0 = time.time()
        try:
            response = await asyncio.to_thread(llm.invoke, messages)
            elapsed = time.time() - t0

            logger.info(
                "[verification_node] node=%s | MODEL OUTPUT ↓ (%.2fs)\n%s",
                node_id,
                elapsed,
                response.content,
            )

            return {
                "verification_type": verification_type,
                "result": "pass",
                "confidence": 0.9,
                "analysis": response.content,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("[verification_node] node=%s | LLM call failed: %s", node_id, e, exc_info=True)
            return {"error": str(e)}

    # ── Decision node ──────────────────────────────────────────────────────────

    async def execute_decision_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id = context.get("current_node_id", "")
        condition_type = node_data.get("conditionType", "threshold")
        threshold = node_data.get("threshold", 0.8)
        custom_prompt = node_data.get("prompt", "")
        previous_output = context.get("previous_output", {})
        llm = self._get_llm()

        if not llm:
            logger.error("[decision_node] node=%s | error=LLM not configured", node_id)
            return {"error": "AI service not configured"}

        logger.info(
            "[decision_node] node=%s | condition_type=%s | threshold=%.2f | invoking LLM",
            node_id, condition_type, threshold,
        )

        # Pass the FULL previous output to the LLM (not _safe_result which truncates).
        # Only strip raw base64 data URIs — they carry no semantic meaning for the decision.
        clean_output = _strip_binaries(previous_output)
        context_text = json.dumps(clean_output, indent=2, ensure_ascii=False)

        system_prompt = (
            "You are a decision-making agent. Carefully read ALL the input data and make a binary decision.\n"
            "You MUST respond with ONLY valid JSON — no markdown, no extra text:\n"
            "{\n"
            '  "decision": "approved" or "rejected",\n'
            '  "confidence": <float 0.0–1.0>,\n'
            '  "reasoning": "<why this decision was made, referencing specific data points>",\n'
            '  "summary": "<one-sentence summary of what was analyzed>",\n'
            '  "key_findings": ["<finding 1>", "<finding 2>", ...]\n'
            "}\n\n"
            f"Decision criteria: {condition_type}. "
            f"Approve ONLY if your confidence is >= {threshold}. "
            "Your decision MUST be based on the actual content of the data provided — do not guess."
        )

        user_prompt = (
            custom_prompt
            or f"Based on the data below, should this be approved or rejected? "
               f"Approve only if your confidence is >= {threshold}. "
               "Explain specifically which data points drove your decision."
        )

        messages = [
            ("system", system_prompt),
            ("user", f"{user_prompt}\n\nInput data from previous step:\n{context_text}"),
        ]

        # Log sanitized version only — never log full data
        logger.info(
            "[decision_node] node=%s | MODEL INPUT ↓\n%s",
            node_id,
            json.dumps(_safe_messages(messages), indent=2, ensure_ascii=False),
        )

        t0 = time.time()
        try:
            response = await asyncio.to_thread(llm.invoke, messages)
            elapsed = time.time() - t0

            logger.info(
                "[decision_node] node=%s | MODEL OUTPUT ↓ (%.2fs)\n%s",
                node_id, elapsed,
                response.content,
            )

            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed = json.loads(raw)
            decision = str(parsed.get("decision", "rejected")).lower()
            confidence = float(parsed.get("confidence", 0.0))
            reasoning = str(parsed.get("reasoning", ""))
            summary = str(parsed.get("summary", ""))
            key_findings = list(parsed.get("key_findings", []))

            logger.info(
                "[decision_node] node=%s | decision=%s | confidence=%.2f | summary=%r",
                node_id, decision, confidence, summary[:200],
            )

            return {
                "decision": decision,
                "confidence": confidence,
                "threshold": threshold,
                "reasoning": reasoning,
                "summary": summary,
                "key_findings": key_findings,
                "_active_handles": [decision],
                "timestamp": datetime.utcnow().isoformat(),
            }

        except json.JSONDecodeError as e:
            raw_text = response.content if 'response' in dir() else ""
            fallback = "approved" if "approved" in raw_text.lower() else "rejected"
            logger.warning(
                "[decision_node] node=%s | JSON parse failed (%s) | fallback=%s | raw=%r",
                node_id, e, fallback, raw_text[:300],
            )
            return {
                "decision": fallback,
                "confidence": 0.5,
                "threshold": threshold,
                "reasoning": f"(JSON parse failed — fallback) {raw_text[:300]}",
                "summary": "",
                "key_findings": [],
                "_active_handles": [fallback],
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("[decision_node] node=%s | LLM call failed: %s", node_id, e, exc_info=True)
            return {"error": str(e)}

    # ── Output node ────────────────────────────────────────────────────────────

    async def execute_output_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id = context.get("current_node_id", "")
        output_type = node_data.get("outputType", "api")
        data = context.get("previous_output", {})

        logger.info("[output_node] node=%s | output_type=%s | data=%s", node_id, output_type, _safe_result(data))

        return {
            "output_type": output_type,
            "data": data,
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ── Message builder ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_data_uri(data_uri: str):
        """Return (mime_type, base64_data) from a data URI."""
        # e.g. "data:application/pdf;base64,JVBERi0x..."
        header, _, b64 = data_uri.partition(",")
        mime = header.replace("data:", "").replace(";base64", "").strip()
        return mime, b64

    def _file_content_part(self, data_uri: str) -> dict:
        """
        Build the correct LangChain content part for a file.

        - Real images (image/*) → {"type": "image_url"} — LangChain validates
          the MIME against image subtypes.
        - PDFs and everything else → {"type": "media"} — maps to Gemini's
          inlineData and accepts any MIME type.
        """
        mime, b64 = self._parse_data_uri(data_uri)
        if mime.startswith("image/"):
            return {"type": "image_url", "image_url": {"url": data_uri}}
        # PDF, DOCX, audio, video, etc.
        return {"type": "media", "data": b64, "mime_type": mime}

    def _build_messages(self, system_prompt: str, user_prompt: str, input_data: Any) -> list:
        # Multi-field path (output of execute_input_node)
        if isinstance(input_data, dict) and "inputs" in input_data:
            all_inputs: Dict[str, Any] = input_data.get("inputs", {})
            filenames: Dict[str, str] = input_data.get("filenames", {})

            file_fields = {k: v for k, v in all_inputs.items()
                           if isinstance(v, str) and v.startswith("data:")}
            text_fields = {k: v for k, v in all_inputs.items() if k not in file_fields}

            text_part = f"{system_prompt}\n\n{user_prompt or 'Analyze the provided inputs.'}"
            if text_fields:
                text_part += f"\n\nText inputs:\n{json.dumps(text_fields, indent=2)}"

            if file_fields:
                file_key, file_value = next(iter(file_fields.items()))
                mime, _ = self._parse_data_uri(file_value)
                fname = filenames.get(file_key)
                if fname:
                    text_part += f"\n\nFile: {fname}"
                logger.info(
                    "_build_messages | mode=multimodal | file_field=%s | mime=%s | text_fields=%s",
                    file_key, mime, list(text_fields.keys()),
                )
                return [HumanMessage(content=[
                    {"type": "text", "text": text_part},
                    self._file_content_part(file_value),
                ])]

            logger.info("_build_messages | mode=text | text_fields=%s", list(text_fields.keys()))
            return [
                ("system", system_prompt),
                ("user", f"{user_prompt}\n\nInput Data:\n{json.dumps(text_fields, indent=2)}"),
            ]

        # Legacy single-value path
        value = input_data.get("value", "") if isinstance(input_data, dict) else str(input_data)
        filename = input_data.get("filename") if isinstance(input_data, dict) else None

        if isinstance(value, str) and value.startswith("data:"):
            mime, _ = self._parse_data_uri(value)
            text = user_prompt or "Analyze this file and extract all relevant information."
            if filename:
                text = f"{text}\n\nFilename: {filename}"
            logger.info("_build_messages | mode=multimodal_legacy | mime=%s", mime)
            return [HumanMessage(content=[
                {"type": "text", "text": f"{system_prompt}\n\n{text}"},
                self._file_content_part(value),
            ])]

        logger.info("_build_messages | mode=text_legacy")
        context_text = (
            json.dumps(input_data, indent=2) if isinstance(input_data, dict) else str(input_data)
        )
        return [
            ("system", system_prompt),
            ("user", f"{user_prompt}\n\nInput Data:\n{context_text}"),
        ]

    def _get_system_prompt(self, task: str) -> str:
        return {
            "extraction":      "You are a data extraction agent. Extract structured information from the input.",
            "classification":  "You are a classification agent. Categorize the input data accurately.",
            "verification":    "You are a verification agent. Verify the consistency and accuracy of the data.",
            "reasoning":       "You are a reasoning agent. Analyze the data and provide detailed insights.",
            "fraud_detection": "You are a fraud detection agent. Identify suspicious patterns.",
            "summarization":   "You are a summarization agent. Condense the input into a clear, concise summary preserving all key facts.",
            "translation":     "You are a translation agent. Accurately translate the input content while preserving meaning and tone. Specify the target language if not given.",
        }.get(task, "You are a helpful AI assistant.")

    # ── Template substitution helper ───────────────────────────────────────────

    @staticmethod
    def _substitute_template(template: str, data: Dict[str, Any]) -> str:
        """Replace {{key}} and {{nested.key}} placeholders with values from data."""
        def replace_match(m: re.Match) -> str:
            key = m.group(1).strip()
            val: Any = data
            for part in key.split('.'):
                val = val.get(part) if isinstance(val, dict) else None
            return str(val) if val is not None else ''
        return re.sub(r'\{\{([^}]+)\}\}', replace_match, template)

    @staticmethod
    def _flatten_previous(previous_output: Any) -> Dict[str, Any]:
        """Extract a flat dict from the previous node's output for template substitution."""
        if not isinstance(previous_output, dict):
            return {}
        if "inputs" in previous_output:
            return previous_output.get("inputs", {})
        if "transformed" in previous_output:
            t = previous_output.get("transformed", {})
            return t if isinstance(t, dict) else previous_output
        if "response" in previous_output and isinstance(previous_output.get("response"), dict):
            return previous_output.get("response", {})
        return previous_output

    # ── HTTP Request node ──────────────────────────────────────────────────────

    async def execute_http_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id = context.get("current_node_id", "")
        method = node_data.get("method", "GET").upper()
        url_template: str = node_data.get("url", "")
        headers_list: List[Dict[str, str]] = node_data.get("headers", [])
        body_template: str = node_data.get("bodyTemplate", "")
        auth_type: str = node_data.get("authType", "none")
        auth_value: str = node_data.get("authValue", "")
        auth_header: str = node_data.get("authHeader", "X-API-Key")
        timeout = int(node_data.get("timeout", 30))

        previous_output = context.get("previous_output", {})
        flat_data = self._flatten_previous(previous_output)

        url = self._substitute_template(url_template, flat_data)

        headers: Dict[str, str] = {}
        for h in headers_list:
            k = h.get("key", "").strip()
            v = self._substitute_template(h.get("value", "").strip(), flat_data)
            if k:
                headers[k] = v

        if auth_type == "bearer" and auth_value:
            headers["Authorization"] = f"Bearer {auth_value}"
        elif auth_type == "apikey" and auth_value:
            headers[auth_header] = auth_value

        body: Any = None
        if method in ("POST", "PUT", "PATCH") and body_template:
            rendered = self._substitute_template(body_template, flat_data)
            try:
                body = json.loads(rendered)
            except json.JSONDecodeError:
                body = rendered

        logger.info(
            "[http_node] node=%s | %s %s | headers_keys=%s | has_body=%s",
            node_id, method, url, list(headers.keys()), body is not None,
        )

        if not url:
            return {"error": "HTTP node requires a URL"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method, url, headers=headers,
                    json=body if isinstance(body, (dict, list)) else None,
                    content=body.encode() if isinstance(body, str) else None,
                )
            logger.info(
                "[http_node] node=%s | status=%d size=%d bytes",
                node_id, response.status_code, len(response.content),
            )
            try:
                response_data: Any = response.json()
            except Exception:
                response_data = response.text

            return {
                "status_code": response.status_code,
                "success": response.is_success,
                "response": response_data,
                "url": url,
                "method": method,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("[http_node] node=%s | request failed: %s", node_id, e, exc_info=True)
            return {"error": f"HTTP request failed: {e}"}

    # ── Transform node ─────────────────────────────────────────────────────────

    async def execute_transform_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id = context.get("current_node_id", "")
        mode = node_data.get("transformMode", "field_map")
        previous_output = context.get("previous_output", {})

        logger.info("[transform_node] node=%s | mode=%s", node_id, mode)

        source = self._flatten_previous(previous_output)

        if mode == "field_map":
            mappings: List[Dict[str, str]] = node_data.get("fieldMappings", [])
            result: Dict[str, Any] = {}
            for m in mappings:
                from_key = m.get("from", "").strip()
                to_key = m.get("to", "").strip()
                if not from_key or not to_key:
                    continue
                val: Any = source
                for part in from_key.split('.'):
                    val = val.get(part) if isinstance(val, dict) else None
                if val is not None:
                    result[to_key] = val
            logger.info("[transform_node] node=%s | field_map | output_keys=%s", node_id, list(result.keys()))
            return {"transformed": result, "source_keys": list(source.keys()), "mode": mode, "timestamp": datetime.utcnow().isoformat()}

        elif mode == "template":
            template_str: str = node_data.get("template", "{}")
            rendered = self._substitute_template(template_str, source)
            try:
                parsed: Any = json.loads(rendered)
            except json.JSONDecodeError:
                parsed = {"rendered": rendered}
            logger.info("[transform_node] node=%s | template | output=%s", node_id, list(parsed.keys()) if isinstance(parsed, dict) else "text")
            return {"transformed": parsed, "mode": mode, "timestamp": datetime.utcnow().isoformat()}

        elif mode == "filter":
            keep = [k.strip() for k in node_data.get("filterKeys", "").split(",") if k.strip()]
            result = {k: v for k, v in source.items() if k in keep}
            logger.info("[transform_node] node=%s | filter | kept_keys=%s", node_id, list(result.keys()))
            return {"transformed": result, "mode": mode, "timestamp": datetime.utcnow().isoformat()}

        else:
            return {"error": f"Unknown transform mode: {mode}"}

    # ── Human Review node ──────────────────────────────────────────────────────

    async def execute_human_review_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id = context.get("current_node_id", "")
        review_prompt = node_data.get("reviewPrompt", "Please review the data below and decide whether to approve or reject.")
        previous_output = context.get("previous_output", {})

        logger.info("[human_review_node] node=%s | HALTING — awaiting human review", node_id)

        clean_data = _strip_binaries(previous_output)

        return {
            "status": "awaiting_review",
            "review_prompt": review_prompt,
            "data_to_review": clean_data,
            "message": "Workflow paused — awaiting human review",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ── Rule Engine node ───────────────────────────────────────────────────────

    @staticmethod
    def _evaluate_rule(actual: Any, operator: str, expected: str) -> bool:
        """Evaluate one rule condition. Returns True if it passes."""
        try:
            op = operator.lower()
            if op == "exists":      return actual is not None
            if op == "not_exists":  return actual is None
            if op == "is_empty":    return not actual
            if op == "is_not_empty": return bool(actual)
            if actual is None:
                return False
            s_a, s_e = str(actual), str(expected)
            if op == "eq":           return s_a == s_e
            if op == "neq":          return s_a != s_e
            if op == "contains":     return s_e.lower() in s_a.lower()
            if op == "not_contains": return s_e.lower() not in s_a.lower()
            if op == "starts_with":  return s_a.lower().startswith(s_e.lower())
            if op == "ends_with":    return s_a.lower().endswith(s_e.lower())
            if op == "regex":        return bool(re.search(s_e, s_a))
            if op == "in_list":      return s_a in [v.strip() for v in s_e.split(",")]
            if op == "not_in_list":  return s_a not in [v.strip() for v in s_e.split(",")]
            n, v = float(actual), float(expected)
            if op == "gt":   return n > v
            if op == "gte":  return n >= v
            if op == "lt":   return n < v
            if op == "lte":  return n <= v
            if op == "between":
                lo, hi = [float(p.strip()) for p in s_e.split(",")]
                return lo <= n <= hi
            return False
        except (ValueError, TypeError, re.error, IndexError):
            return False

    async def execute_rule_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate physical business rules (no LLM). Routes via 'pass'/'fail' handles."""
        node_id = context.get("current_node_id", "")
        rules: List[Dict] = node_data.get("rules", [])
        combine_mode: str = node_data.get("combineMode", "AND")
        previous_output = context.get("previous_output", {})

        logger.info("[rule_node] node=%s | rules=%d mode=%s", node_id, len(rules), combine_mode)
        flat = self._flatten_previous(previous_output)
        matched: List[str] = []
        failed: List[str] = []

        for rule in rules:
            field     = rule.get("field", "")
            operator  = rule.get("operator", "eq")
            expected  = str(rule.get("value", ""))
            label     = rule.get("label") or f"{field} {operator} {expected}"
            val: Any  = flat
            for part in field.split('.'):
                val = val.get(part) if isinstance(val, dict) else None
            (matched if self._evaluate_rule(val, operator, expected) else failed).append(label)

        passed = (len(matched) > 0) if combine_mode == "OR" else (len(failed) == 0 and len(rules) > 0)
        route  = "pass" if passed else "fail"
        logger.info("[rule_node] node=%s | result=%s matched=%s failed=%s", node_id, route, matched, failed)

        return {
            "passed":        passed,
            "route":         route,
            "matched_rules": matched,
            "failed_rules":  failed,
            "combine_mode":  combine_mode,
            "rule_count":    len(rules),
            "data":          previous_output,
            "_active_handles": [route],
            "timestamp":     datetime.utcnow().isoformat(),
        }

    # ── Code Runner node ───────────────────────────────────────────────────────

    async def execute_code_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Run a custom Python snippet. Receives `input_data`; must assign `output`."""
        import math
        import datetime as dt

        node_id   = context.get("current_node_id", "")
        code: str = node_data.get("code", "output = input_data")
        timeout_s = int(node_data.get("timeout", 10))
        previous_output = context.get("previous_output", {})

        logger.info("[code_node] node=%s | lines=%d timeout=%ds", node_id, code.count("\n") + 1, timeout_s)

        safe_builtins: Dict[str, Any] = {
            "len": len, "range": range, "enumerate": enumerate,
            "list": list, "dict": dict, "str": str, "int": int, "float": float,
            "bool": bool, "set": set, "tuple": tuple,
            "sorted": sorted, "reversed": reversed,
            "sum": sum, "min": min, "max": max, "abs": abs, "round": round,
            "zip": zip, "map": map, "filter": filter, "any": any, "all": all,
            "print": print, "repr": repr,
            "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
            "type": type, "None": None, "True": True, "False": False,
        }
        exec_globals: Dict[str, Any] = {
            "__builtins__": safe_builtins,
            "json": json, "re": re, "math": math, "datetime": dt,
            "input_data": previous_output,
            "output": None,
        }

        def _run() -> Any:
            exec(code, exec_globals)  # noqa: S102
            return exec_globals.get("output")

        try:
            output_val = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout_s)
            logger.info("[code_node] node=%s | output_type=%s", node_id, type(output_val).__name__)
            return {"output": output_val, "executed": True, "timestamp": datetime.utcnow().isoformat()}
        except asyncio.TimeoutError:
            return {"error": f"Code execution timed out after {timeout_s}s"}
        except Exception as e:
            logger.error("[code_node] node=%s | %s: %s", node_id, type(e).__name__, e)
            return {"error": f"{type(e).__name__}: {e}"}

    # ── Schema Validator node ──────────────────────────────────────────────────

    async def execute_validator_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate fields in previous output against configurable rules (no LLM)."""
        node_id = context.get("current_node_id", "")
        validation_rules: List[Dict] = node_data.get("validationRules", [])
        previous_output = context.get("previous_output", {})

        logger.info("[validator_node] node=%s | rules=%d", node_id, len(validation_rules))
        flat = self._flatten_previous(previous_output)
        errors: List[str] = []

        for rule in validation_rules:
            field      = rule.get("field", "")
            required   = rule.get("required", False)
            field_type = rule.get("fieldType", "")
            pattern    = rule.get("pattern", "")
            min_val    = rule.get("min")
            max_val    = rule.get("max")
            min_len    = rule.get("minLength")
            max_len    = rule.get("maxLength")
            enum_str   = rule.get("enum", "")

            val: Any = flat
            for part in field.split('.'):
                val = val.get(part) if isinstance(val, dict) else None

            if required and (val is None or val == ""):
                errors.append(f"'{field}' is required but missing")
                continue
            if val is None:
                continue

            if field_type == "number":
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    errors.append(f"'{field}' must be a number, got {repr(val)[:40]}"); continue
            elif field_type == "boolean" and str(val).lower() not in ("true", "false", "1", "0"):
                errors.append(f"'{field}' must be boolean")
            elif field_type == "array" and not isinstance(val, list):
                errors.append(f"'{field}' must be an array")
            elif field_type == "object" and not isinstance(val, dict):
                errors.append(f"'{field}' must be an object")

            if pattern:
                try:
                    if not re.search(pattern, str(val)):
                        errors.append(f"'{field}' does not match pattern {pattern!r}")
                except re.error:
                    errors.append(f"'{field}' — invalid regex: {pattern!r}")

            try:
                n = float(val)
                if min_val is not None and n < float(min_val):
                    errors.append(f"'{field}' ({val}) is below minimum {min_val}")
                if max_val is not None and n > float(max_val):
                    errors.append(f"'{field}' ({val}) exceeds maximum {max_val}")
            except (ValueError, TypeError):
                pass

            try:
                length = len(str(val)) if isinstance(val, str) else len(val)
                if min_len is not None and length < int(min_len):
                    errors.append(f"'{field}' length {length} < minimum {min_len}")
                if max_len is not None and length > int(max_len):
                    errors.append(f"'{field}' length {length} > maximum {max_len}")
            except (TypeError, ValueError):
                pass

            if enum_str:
                allowed = [v.strip() for v in enum_str.split(",") if v.strip()]
                if str(val) not in allowed:
                    errors.append(f"'{field}' {repr(str(val))[:30]} not in {allowed}")

        passed = len(errors) == 0
        logger.info("[validator_node] node=%s | passed=%s errors=%d", node_id, passed, len(errors))

        if not passed:
            return {
                "passed": False, "errors": errors, "rule_count": len(validation_rules),
                "error": f"Validation failed ({len(errors)} error{'s' if len(errors)!=1 else ''}): {errors[0]}",
                "timestamp": datetime.utcnow().isoformat(),
            }
        return {
            "passed": True, "errors": [], "rule_count": len(validation_rules),
            "data": previous_output, "timestamp": datetime.utcnow().isoformat(),
        }

    # ── Switch Router node ─────────────────────────────────────────────────────

    async def execute_switch_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Route to one of N branches by field value. Uses '|' for OR values. No LLM."""
        node_id      = context.get("current_node_id", "")
        switch_field = node_data.get("switchField", "")
        cases: List[Dict] = node_data.get("cases", [])
        previous_output   = context.get("previous_output", {})

        flat = self._flatten_previous(previous_output)
        val: Any = flat
        for part in switch_field.split('.'):
            val = val.get(part) if isinstance(val, dict) else None

        matched_handle = "default"
        matched_label  = "default"
        for case in cases:
            match_values = [v.strip() for v in str(case.get("matchValue", "")).split("|")]
            if str(val) in match_values:
                matched_handle = case.get("handle", "case_0")
                matched_label  = case.get("label") or case.get("matchValue", "")
                break

        logger.info(
            "[switch_node] node=%s | field=%s value=%r routed_to=%s",
            node_id, switch_field, val, matched_handle,
        )
        return {
            "routed_to":     matched_handle,
            "matched_case":  matched_label,
            "switch_field":  switch_field,
            "switch_value":  val,
            "data":          previous_output,
            "_active_handles": [matched_handle],
            "timestamp":     datetime.utcnow().isoformat(),
        }

    # ── Formatter node ─────────────────────────────────────────────────────────

    async def execute_formatter_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Render a text/HTML/Markdown template with {{variable}} substitution from previous output."""
        node_id          = context.get("current_node_id", "")
        template: str    = node_data.get("template", "")
        output_format    = node_data.get("outputFormat", "text")
        subject_template = node_data.get("subjectTemplate", "")
        previous_output  = context.get("previous_output", {})

        logger.info("[formatter_node] node=%s | format=%s | len=%d", node_id, output_format, len(template))
        flat = self._flatten_previous(previous_output)

        return {
            "rendered":  self._substitute_template(template, flat),
            "subject":   self._substitute_template(subject_template, flat) if subject_template else "",
            "format":    output_format,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ── Aggregator node ────────────────────────────────────────────────────────

    async def execute_aggregator_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Compute sum/avg/count/min/max/join/unique/group_by over an array in previous output."""
        node_id      = context.get("current_node_id", "")
        source_field = node_data.get("sourceField", "")
        operation    = node_data.get("operation", "count")
        value_field  = node_data.get("valueField", "")
        group_by     = node_data.get("groupBy", "")
        separator    = node_data.get("separator", ", ")
        previous_output = context.get("previous_output", {})

        logger.info("[aggregator_node] node=%s | op=%s field=%s", node_id, operation, source_field)
        flat = self._flatten_previous(previous_output)

        arr: Any = flat
        if source_field:
            for part in source_field.split('.'):
                arr = arr.get(part) if isinstance(arr, dict) else None
        if arr is None:
            arr = list(flat.values())[0] if flat else []
        if not isinstance(arr, list):
            arr = [arr]

        def _val(item: Any) -> Any:
            if value_field and isinstance(item, dict):
                v = item
                for p in value_field.split('.'):
                    v = v.get(p) if isinstance(v, dict) else None
                return v
            return item

        values = [_val(i) for i in arr]
        nums = [float(v) for v in values if v is not None and str(v).replace('.','',1).lstrip('-').isdigit()]

        agg: Any
        if   operation == "count":    agg = len(arr)
        elif operation == "sum":      agg = sum(nums)
        elif operation == "avg":      agg = round(sum(nums) / len(nums), 4) if nums else 0
        elif operation == "min":      agg = min(nums) if nums else None
        elif operation == "max":      agg = max(nums) if nums else None
        elif operation == "first":    agg = arr[0] if arr else None
        elif operation == "last":     agg = arr[-1] if arr else None
        elif operation == "join":     agg = separator.join(str(v) for v in values if v is not None)
        elif operation == "unique":   agg = list(dict.fromkeys(str(v) for v in values if v is not None))
        elif operation == "group_by":
            groups: Dict[str, List] = {}
            for item in arr:
                key = str(item.get(group_by, "") if isinstance(item, dict) and group_by else _val(item))
                groups.setdefault(key, []).append(item)
            agg = groups
        else:
            agg = len(arr)

        logger.info("[aggregator_node] node=%s | result=%s", node_id, str(agg)[:80])
        return {
            "result":       agg,
            "operation":    operation,
            "source_field": source_field,
            "item_count":   len(arr),
            "timestamp":    datetime.utcnow().isoformat(),
        }

    # ── Indian KYC node ────────────────────────────────────────────────────────

    _SUREPASS_ENDPOINTS: Dict[str, str] = {
        "pan":              "https://kyc-api.surepass.io/api/v1/pan/pan",
        "aadhaar":          "https://kyc-api.surepass.io/api/v1/aadhaar-v2/generate-otp",
        "voter_id":         "https://kyc-api.surepass.io/api/v1/voter-id/voter-id",
        "driving_license":  "https://kyc-api.surepass.io/api/v1/driving-license/driving-license",
        "passport":         "https://kyc-api.surepass.io/api/v1/passport/file-number",
    }

    _IDFY_ENDPOINTS: Dict[str, str] = {
        "pan":              "https://eve.idfy.com/v3/tasks/sync/verify_with_source/ind_pan",
        "aadhaar":          "https://eve.idfy.com/v3/tasks/sync/verify_with_source/ind_aadhaar",
        "voter_id":         "https://eve.idfy.com/v3/tasks/sync/verify_with_source/ind_voter_id",
        "driving_license":  "https://eve.idfy.com/v3/tasks/sync/verify_with_source/ind_driving_license",
        "passport":         "https://eve.idfy.com/v3/tasks/sync/verify_with_source/ind_passport",
    }

    _SANDBOX_ENDPOINTS: Dict[str, str] = {
        "pan":              "https://api.sandbox.co.in/kyc/pan/verify",
        "aadhaar":          "https://api.sandbox.co.in/kyc/aadhaar/otp",
        "voter_id":         "https://api.sandbox.co.in/kyc/voter-id/verify",
        "driving_license":  "https://api.sandbox.co.in/kyc/driving-license/verify",
        "passport":         "https://api.sandbox.co.in/kyc/passport/verify",
    }

    _KARZA_ENDPOINTS: Dict[str, str] = {
        "pan":              "https://api.karza.in/v3/pan/verify",
        "aadhaar":          "https://api.karza.in/v3/aadhaar/generate-otp",
        "voter_id":         "https://api.karza.in/v3/voter-id/verify",
        "driving_license":  "https://api.karza.in/v3/dl/verify",
        "passport":         "https://api.karza.in/v3/passport/verify",
    }

    def _build_kyc_request(
        self,
        provider: str,
        doc_type: str,
        doc_number: str,
        api_key: str,
        custom_endpoint: str,
    ) -> tuple:
        """Return (url, headers, body) for the given provider and document type."""
        if provider == "surepass":
            url = self._SUREPASS_ENDPOINTS.get(doc_type, "")
            headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
            body = {"id_number": doc_number}
            return url, headers, body

        if provider == "idfy":
            import uuid
            url = self._IDFY_ENDPOINTS.get(doc_type, "")
            headers = {
                "account-id": api_key.split(":")[0] if ":" in api_key else api_key,
                "api-key": api_key.split(":")[1] if ":" in api_key else api_key,
                "Content-Type": "application/json",
            }
            body = {
                "task_id": str(uuid.uuid4()),
                "group_id": str(uuid.uuid4()),
                "data": {"id_number": doc_number},
            }
            return url, headers, body

        if provider == "sandbox":
            url = self._SANDBOX_ENDPOINTS.get(doc_type, "")
            headers = {
                "Authorization": api_key,
                "x-api-key": api_key,
                "x-api-version": "1.0",
                "Content-Type": "application/json",
            }
            body = {"pan": doc_number} if doc_type == "pan" else {"id_number": doc_number}
            return url, headers, body

        if provider == "karza":
            url = self._KARZA_ENDPOINTS.get(doc_type, "")
            headers = {"x-karza-key": api_key, "Content-Type": "application/json"}
            body = {"id_number": doc_number}
            return url, headers, body

        # custom provider
        return custom_endpoint, {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, {"id_number": doc_number}

    @staticmethod
    def _normalize_kyc_response(provider: str, doc_type: str, raw: Any, status_code: int) -> Dict[str, Any]:
        """Extract common fields from provider-specific responses into a standard shape."""
        kyc_data: Dict[str, Any] = {}
        verified = False

        if provider == "surepass":
            success = raw.get("success", False)
            verified = success and status_code in (200, 101)
            data = raw.get("data", {})
            kyc_data = {
                "name": data.get("full_name") or data.get("name", ""),
                "dob": data.get("dob", ""),
                "gender": data.get("gender", ""),
                "address": data.get("address") or data.get("address_data", {}),
                "father_name": data.get("father_name", ""),
                "category": data.get("category", ""),
                "status": data.get("status", ""),
            }

        elif provider == "idfy":
            result = raw.get("result", {})
            details = result.get("details", {})
            verified = result.get("status", "") in ("id_found", "verified") and status_code == 200
            kyc_data = {
                "name": details.get("name", ""),
                "dob": details.get("dob", ""),
                "gender": details.get("gender", ""),
                "address": details.get("address", {}),
                "status": result.get("status", ""),
            }

        elif provider == "sandbox":
            data = raw.get("data", raw)
            verified = raw.get("code", 0) == 200 or status_code == 200
            kyc_data = {
                "name": data.get("name", "") or data.get("full_name", ""),
                "dob": data.get("dob", "") or data.get("date_of_birth", ""),
                "gender": data.get("gender", ""),
                "address": data.get("address", ""),
            }

        elif provider == "karza":
            result = raw.get("result", [{}])
            details = result[0] if isinstance(result, list) and result else {}
            verified = raw.get("statusCode", 0) == 101 and status_code == 200
            kyc_data = {
                "name": details.get("name", ""),
                "dob": details.get("dob", ""),
                "father_name": details.get("fatherName", ""),
                "address": details.get("address", ""),
            }

        else:
            # custom / unknown: pass raw through
            verified = status_code == 200
            kyc_data = raw if isinstance(raw, dict) else {}

        # Strip None/empty to keep output clean
        kyc_data = {k: v for k, v in kyc_data.items() if v not in (None, "", {})}

        return {
            "verified": verified,
            "document_type": doc_type,
            "provider": provider,
            "kyc_data": kyc_data,
            "raw_response": raw,
            "status_code": status_code,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def execute_indian_kyc_node(self, node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        node_id      = context.get("current_node_id", "")
        doc_type     = node_data.get("documentType", "pan")
        provider     = node_data.get("provider", "surepass")
        api_key      = node_data.get("apiKey", "")
        doc_field    = node_data.get("documentField", "document_number")
        custom_ep    = node_data.get("customEndpoint", "")

        previous_output = context.get("previous_output", {})
        flat = self._flatten_previous(previous_output)

        # Extract document number using dot notation path
        doc_number: Any = flat
        for part in doc_field.split('.'):
            doc_number = doc_number.get(part) if isinstance(doc_number, dict) else None

        if not doc_number:
            return {"error": f"Indian KYC node: document number not found at field '{doc_field}' in previous output"}

        doc_number = str(doc_number).strip()
        logger.info(
            "[indian_kyc_node] node=%s | doc_type=%s provider=%s field=%s number=%s",
            node_id, doc_type, provider, doc_field, doc_number[:4] + "****",
        )

        if not api_key and provider != "custom":
            return {"error": f"Indian KYC node: apiKey is required for provider '{provider}'"}

        url, headers, body = self._build_kyc_request(provider, doc_type, doc_number, api_key, custom_ep)

        if not url:
            return {"error": f"Indian KYC node: no endpoint configured for provider='{provider}' docType='{doc_type}'"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=body, headers=headers)

            logger.info(
                "[indian_kyc_node] node=%s | status=%d size=%d",
                node_id, response.status_code, len(response.content),
            )

            try:
                raw = response.json()
            except Exception:
                raw = {"raw_text": response.text}

            result = self._normalize_kyc_response(provider, doc_type, raw, response.status_code)
            logger.info(
                "[indian_kyc_node] node=%s | verified=%s kyc_keys=%s",
                node_id, result["verified"], list(result["kyc_data"].keys()),
            )
            return result

        except Exception as e:
            logger.error("[indian_kyc_node] node=%s | request failed: %s", node_id, e, exc_info=True)
            return {"error": f"Indian KYC request failed: {e}"}


# ── Workflow orchestrator ──────────────────────────────────────────────────────

class WorkflowExecutor:

    def __init__(self):
        self.node_executor = NodeExecutor()

    async def execute_workflow(
        self,
        graph_data: Dict[str, Any],
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        nodes: List[Dict] = graph_data.get("nodes", [])
        edges: List[Dict] = graph_data.get("edges", [])
        node_map: Dict[str, Dict] = {n["id"]: n for n in nodes}

        # Index incoming edges per target node
        incoming: Dict[str, List[Dict]] = {n["id"]: [] for n in nodes}
        for edge in edges:
            if edge["target"] in incoming:
                incoming[edge["target"]].append(edge)

        fired_edges: set = set()                                       # edge IDs that have activated
        ready: List[str] = [n["id"] for n in nodes if not incoming[n["id"]]]  # roots

        logger.info(
            "=== WORKFLOW START | nodes=%d edges=%d roots=%s ===",
            len(nodes), len(edges), ready,
        )

        execution_trace: List[Dict] = []
        context: Dict[str, Any] = {"input": input_data, "previous_output": input_data or {}}
        workflow_start = time.time()
        executed: set = set()

        while ready:
            node_id = ready.pop(0)
            if node_id in executed:
                continue

            node = node_map.get(node_id)
            if not node:
                logger.warning("Node %s not in graph — skipping", node_id)
                continue

            node_type  = node["type"]
            node_label = node.get("data", {}).get("label", node_id)
            logger.info("--- NODE START | id=%s type=%s label=%r ---", node_id, node_type, node_label)
            node_start = time.time()

            context["current_node_id"] = node_id
            result = await self._execute_node(node_type, node.get("data", {}), context)
            elapsed = time.time() - node_start
            has_error = "error" in result

            logger.info(
                "--- NODE END | id=%s type=%s label=%r | %s %.2fs | result=%s ---",
                node_id, node_type, node_label,
                "ERROR" if has_error else "OK",
                elapsed,
                json.dumps(_safe_result(result), ensure_ascii=False)[:300],
            )

            execution_trace.append({
                "node_id":   node_id,
                "node_type": node_type,
                "result":    result,
                "timestamp": datetime.utcnow().isoformat(),
            })
            executed.add(node_id)

            if has_error:
                total = time.time() - workflow_start
                logger.error(
                    "=== WORKFLOW HALTED | node=%s (%s) error=%r | %.2fs ===",
                    node_id, node_type, result["error"], total,
                )
                return {
                    "status":            "failed",
                    "failed_node_id":    node_id,
                    "failed_node_type":  node_type,
                    "failed_node_label": node_label,
                    "error":             result["error"],
                    "execution_trace":   execution_trace,
                    "final_output":      None,
                    "timestamp":         datetime.utcnow().isoformat(),
                }

            if result.get("status") == "awaiting_review":
                total = time.time() - workflow_start
                logger.info(
                    "=== WORKFLOW PAUSED | node=%s (%s) awaiting review | %.2fs ===",
                    node_id, node_type, total,
                )
                return {
                    "status":            "paused",
                    "paused_node_id":    node_id,
                    "paused_node_type":  node_type,
                    "paused_node_label": node_label,
                    "review_data":       result,
                    "execution_trace":   execution_trace,
                    "final_output":      result,
                    "timestamp":         datetime.utcnow().isoformat(),
                }

            context["previous_output"] = result

            # ── Conditional edge routing via _active_handles ───────────────────
            active_handles: Optional[List[str]] = result.get("_active_handles")
            outgoing = [e for e in edges if e["source"] == node_id]
            if active_handles is not None:
                active_out = [e for e in outgoing if e.get("sourceHandle") in active_handles]
                skipped = len(outgoing) - len(active_out)
                if skipped:
                    logger.info(
                        "[routing] node=%s active=%s fires=%d skips=%d",
                        node_id, active_handles, len(active_out), skipped,
                    )
            else:
                active_out = outgoing  # non-routing node: all edges fire

            for edge in active_out:
                fired_edges.add(edge["id"])

            # Enqueue downstream nodes whose ALL incoming edges have now fired
            for edge in active_out:
                target = edge["target"]
                if target in executed:
                    continue
                if all(e["id"] in fired_edges for e in incoming.get(target, [])):
                    ready.append(target)

        total = time.time() - workflow_start
        logger.info(
            "=== WORKFLOW END | %.2fs | executed=%d/%d nodes ===",
            total, len(executed), len(nodes),
        )
        return {
            "status":          "completed",
            "execution_trace": execution_trace,
            "final_output":    context.get("previous_output", {}),
            "timestamp":       datetime.utcnow().isoformat(),
        }

    async def _execute_node(
        self, node_type: str, node_data: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        executor_map = {
            "inputNode":        self.node_executor.execute_input_node,
            "aiNode":           self.node_executor.execute_ai_node,
            "verificationNode": self.node_executor.execute_verification_node,
            "decisionNode":     self.node_executor.execute_decision_node,
            "outputNode":       self.node_executor.execute_output_node,
            "httpNode":         self.node_executor.execute_http_node,
            "transformNode":    self.node_executor.execute_transform_node,
            "humanReviewNode":  self.node_executor.execute_human_review_node,
            "ruleNode":         self.node_executor.execute_rule_node,
            "codeNode":         self.node_executor.execute_code_node,
            "validatorNode":    self.node_executor.execute_validator_node,
            "switchNode":       self.node_executor.execute_switch_node,
            "formatterNode":    self.node_executor.execute_formatter_node,
            "aggregatorNode":   self.node_executor.execute_aggregator_node,
            "indianKycNode":    self.node_executor.execute_indian_kyc_node,
        }
        executor = executor_map.get(node_type)
        if not executor:
            logger.error("Unknown node type: %s", node_type)
            return {"error": f"Unknown node type: {node_type}"}
        return await executor(node_data, context)
