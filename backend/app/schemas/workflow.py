from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID

class NodeData(BaseModel):
    id: str
    type: str
    position: Dict[str, float]
    data: Dict[str, Any]

class EdgeData(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None

class GraphData(BaseModel):
    nodes: List[NodeData]
    edges: List[EdgeData]

class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    graph_data: GraphData

class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    graph_data: Optional[GraphData] = None
    status: Optional[str] = None

class WorkflowResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    graph_data: Dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
    version: str

    class Config:
        from_attributes = True

class TriggerResponse(BaseModel):
    workflow_id: UUID
    execution_id: UUID
    status: str
    output: Optional[Dict[str, Any]]

class ExecutionCreate(BaseModel):
    workflow_id: UUID
    input_data: Optional[Dict[str, Any]] = None

class ExecutionResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    status: str
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    execution_trace: Optional[List[Dict[str, Any]]]
    error_message: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True
