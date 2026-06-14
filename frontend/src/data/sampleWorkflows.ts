import { Node, Edge } from 'reactflow';

export interface SampleWorkflow {
  name: string;
  description: string;
  nodes: Node[];
  edges: Edge[];
}

export const sampleWorkflows: SampleWorkflow[] = [
  {
    name: 'KYC Verification',
    description: 'Identity verification pipeline for fintech customer onboarding.',
    nodes: [
      {
        id: 'kyc_1',
        type: 'inputNode',
        position: { x: 60, y: 160 },
        data: {
          label: 'Customer Data',
          description: 'Customer ID + identity document',
          fields: [
            { id: 'kyc_f1', name: 'customer_id', type: 'text' },
            { id: 'kyc_f2', name: 'full_name', type: 'text' },
            { id: 'kyc_f3', name: 'identity_document', type: 'file' },
          ],
        },
      },
      {
        id: 'kyc_2',
        type: 'aiNode',
        position: { x: 280, y: 160 },
        data: { label: 'Extract Info', aiTask: 'extraction', prompt: 'Extract customer identity details from submitted documents' },
      },
      {
        id: 'kyc_3',
        type: 'verificationNode',
        position: { x: 500, y: 160 },
        data: { label: 'Identity Check', verificationType: 'compliance', description: 'Cross-verify identity fields' },
      },
      {
        id: 'kyc_4',
        type: 'decisionNode',
        position: { x: 720, y: 160 },
        data: { label: 'Approve?', conditionType: 'threshold', threshold: 0.8 },
      },
      {
        id: 'kyc_5',
        type: 'outputNode',
        position: { x: 940, y: 160 },
        data: { label: 'KYC Result', outputType: 'notification' },
      },
    ],
    edges: [
      { id: 'e_kyc_1', source: 'kyc_1', target: 'kyc_2' },
      { id: 'e_kyc_2', source: 'kyc_2', target: 'kyc_3' },
      { id: 'e_kyc_3', source: 'kyc_3', target: 'kyc_4' },
      { id: 'e_kyc_4', source: 'kyc_4', target: 'kyc_5', sourceHandle: 'approved' },
    ],
  },
  {
    name: 'Fraud Detection',
    description: 'Real-time transaction fraud scoring and risk alerting.',
    nodes: [
      {
        id: 'fd_1',
        type: 'inputNode',
        position: { x: 60, y: 160 },
        data: {
          label: 'Transaction',
          description: 'Incoming payment data',
          fields: [
            { id: 'fd_f1', name: 'transaction_id', type: 'text' },
            { id: 'fd_f2', name: 'amount', type: 'number' },
            { id: 'fd_f3', name: 'transaction_data', type: 'json' },
          ],
        },
      },
      {
        id: 'fd_2',
        type: 'aiNode',
        position: { x: 280, y: 160 },
        data: { label: 'Pattern Analysis', aiTask: 'reasoning', prompt: 'Analyze transaction patterns and flag anomalies' },
      },
      {
        id: 'fd_3',
        type: 'aiNode',
        position: { x: 500, y: 160 },
        data: { label: 'Fraud Score', aiTask: 'fraud_detection', prompt: 'Calculate fraud probability based on detected patterns' },
      },
      {
        id: 'fd_4',
        type: 'decisionNode',
        position: { x: 720, y: 160 },
        data: { label: 'Risk Threshold', conditionType: 'threshold', threshold: 0.7 },
      },
      {
        id: 'fd_5',
        type: 'outputNode',
        position: { x: 940, y: 160 },
        data: { label: 'Risk Alert', outputType: 'notification' },
      },
    ],
    edges: [
      { id: 'e_fd_1', source: 'fd_1', target: 'fd_2' },
      { id: 'e_fd_2', source: 'fd_2', target: 'fd_3' },
      { id: 'e_fd_3', source: 'fd_3', target: 'fd_4' },
      { id: 'e_fd_4', source: 'fd_4', target: 'fd_5', sourceHandle: 'approved' },
    ],
  },
  {
    name: 'Document Processing',
    description: 'OCR extraction, classification, and compliance verification.',
    nodes: [
      {
        id: 'dp_1',
        type: 'inputNode',
        position: { x: 60, y: 160 },
        data: {
          label: 'File Upload',
          description: 'PDF or image document',
          fields: [
            { id: 'dp_f1', name: 'document', type: 'file' },
            { id: 'dp_f2', name: 'document_type', type: 'text' },
          ],
        },
      },
      {
        id: 'dp_2',
        type: 'aiNode',
        position: { x: 280, y: 160 },
        data: { label: 'OCR Extract', aiTask: 'extraction', outputFormat: 'text', temperature: 0.2, prompt: 'Extract all text and structured fields from the document' },
      },
      {
        id: 'dp_3',
        type: 'aiNode',
        position: { x: 500, y: 160 },
        data: { label: 'Classify Doc', aiTask: 'classification', outputFormat: 'text', temperature: 0.3, prompt: 'Classify document type and validate its structure' },
      },
      {
        id: 'dp_4',
        type: 'verificationNode',
        position: { x: 720, y: 160 },
        data: { label: 'Compliance', verificationType: 'compliance', description: 'Regulatory requirement check' },
      },
      {
        id: 'dp_5',
        type: 'outputNode',
        position: { x: 940, y: 160 },
        data: { label: 'Report', outputType: 'report' },
      },
    ],
    edges: [
      { id: 'e_dp_1', source: 'dp_1', target: 'dp_2' },
      { id: 'e_dp_2', source: 'dp_2', target: 'dp_3' },
      { id: 'e_dp_3', source: 'dp_3', target: 'dp_4' },
      { id: 'e_dp_4', source: 'dp_4', target: 'dp_5' },
    ],
  },
  {
    name: 'API Enrichment + Review',
    description: 'Fetch external data, transform it, then pause for human review before acting.',
    nodes: [
      {
        id: 'ae_1',
        type: 'inputNode',
        position: { x: 60, y: 180 },
        data: {
          label: 'Entity Input',
          description: 'Entity to look up',
          fields: [
            { id: 'ae_f1', name: 'entity_id', type: 'text' },
            { id: 'ae_f2', name: 'entity_type', type: 'text' },
          ],
        },
      },
      {
        id: 'ae_2',
        type: 'httpNode',
        position: { x: 280, y: 180 },
        data: {
          label: 'Fetch Profile',
          method: 'GET',
          url: 'https://jsonplaceholder.typicode.com/users/{{entity_id}}',
          headers: [],
          authType: 'none',
          authValue: '',
          authHeader: 'X-API-Key',
          bodyTemplate: '',
          timeout: 30,
        },
      },
      {
        id: 'ae_3',
        type: 'transformNode',
        position: { x: 500, y: 180 },
        data: {
          label: 'Extract Fields',
          transformMode: 'field_map',
          fieldMappings: [
            { id: 'ae_m1', from: 'name', to: 'display_name' },
            { id: 'ae_m2', from: 'email', to: 'contact_email' },
            { id: 'ae_m3', from: 'company.name', to: 'company' },
          ],
          template: '{}',
          filterKeys: '',
        },
      },
      {
        id: 'ae_4',
        type: 'aiNode',
        position: { x: 720, y: 180 },
        data: {
          label: 'Risk Analysis',
          aiTask: 'reasoning',
          outputFormat: 'text',
          temperature: 0.5,
          prompt: 'Analyze this entity profile and assess any risk factors based on the available data.',
        },
      },
      {
        id: 'ae_5',
        type: 'humanReviewNode',
        position: { x: 940, y: 180 },
        data: {
          label: 'Analyst Review',
          reviewPrompt: 'Review the AI risk analysis below. Verify the entity details and approve or reject before proceeding.',
        },
      },
      {
        id: 'ae_6',
        type: 'outputNode',
        position: { x: 1160, y: 180 },
        data: { label: 'Record Decision', outputType: 'database' },
      },
    ],
    edges: [
      { id: 'e_ae_1', source: 'ae_1', target: 'ae_2' },
      { id: 'e_ae_2', source: 'ae_2', target: 'ae_3' },
      { id: 'e_ae_3', source: 'ae_3', target: 'ae_4' },
      { id: 'e_ae_4', source: 'ae_4', target: 'ae_5' },
      { id: 'e_ae_5', source: 'ae_5', target: 'ae_6' },
    ],
  },
  {
    name: 'Loan Eligibility',
    description: 'Validate applicant data, apply eligibility rules, AI analysis, then decision routing.',
    nodes: [
      {
        id: 'le_1',
        type: 'inputNode',
        position: { x: 60, y: 200 },
        data: {
          label: 'Applicant Data',
          description: 'Loan application fields',
          fields: [
            { id: 'le_f1', name: 'applicant_name', type: 'text' },
            { id: 'le_f2', name: 'annual_income', type: 'number' },
            { id: 'le_f3', name: 'credit_score', type: 'number' },
            { id: 'le_f4', name: 'loan_amount', type: 'number' },
            { id: 'le_f5', name: 'employment_status', type: 'text' },
          ],
        },
      },
      {
        id: 'le_2',
        type: 'validatorNode',
        position: { x: 280, y: 200 },
        data: {
          label: 'Field Validation',
          validationRules: [
            { id: 'le_v1', field: 'annual_income', required: 'true', fieldType: 'number', min: '1000' },
            { id: 'le_v2', field: 'credit_score', required: 'true', fieldType: 'number', min: '300', max: '850' },
            { id: 'le_v3', field: 'loan_amount', required: 'true', fieldType: 'number', min: '1000' },
            { id: 'le_v4', field: 'employment_status', required: 'true', enum: 'employed,self-employed,retired' },
          ],
        },
      },
      {
        id: 'le_3',
        type: 'ruleNode',
        position: { x: 500, y: 200 },
        data: {
          label: 'Eligibility Rules',
          combineMode: 'AND',
          rules: [
            { id: 'le_r1', field: 'credit_score', operator: 'gte', value: '650', label: 'Min credit score' },
            { id: 'le_r2', field: 'annual_income', operator: 'gte', value: '30000', label: 'Min income' },
            { id: 'le_r3', field: 'employment_status', operator: 'in_list', value: 'employed,self-employed,retired', label: 'Employment check' },
          ],
        },
      },
      {
        id: 'le_4',
        type: 'aiNode',
        position: { x: 740, y: 160 },
        data: {
          label: 'Risk Analysis',
          aiTask: 'reasoning',
          outputFormat: 'json',
          temperature: 0.3,
          prompt: 'Analyze this loan application. Assess risk level (low/medium/high), debt-to-income ratio estimate, and provide a recommendation with key factors.',
        },
      },
      {
        id: 'le_5',
        type: 'decisionNode',
        position: { x: 960, y: 160 },
        data: { label: 'Final Decision', conditionType: 'threshold', threshold: 0.7, prompt: 'Approve the loan if the applicant meets eligibility criteria and risk analysis shows low to medium risk.' },
      },
      {
        id: 'le_6',
        type: 'formatterNode',
        position: { x: 1180, y: 100 },
        data: {
          label: 'Approval Letter',
          outputFormat: 'email',
          subjectTemplate: 'Loan Approved: {{applicant_name}}',
          template: 'Dear {{applicant_name}},\n\nWe are pleased to inform you that your loan application has been approved.\n\nLoan Amount: {{loan_amount}}\nApplicant: {{applicant_name}}\n\nBest regards,\nLoan Team',
        },
      },
      {
        id: 'le_7',
        type: 'outputNode',
        position: { x: 1400, y: 100 },
        data: { label: 'Send Approval', outputType: 'email' },
      },
      {
        id: 'le_8',
        type: 'outputNode',
        position: { x: 1180, y: 280 },
        data: { label: 'Rejection Notice', outputType: 'notification' },
      },
    ],
    edges: [
      { id: 'e_le_1', source: 'le_1', target: 'le_2' },
      { id: 'e_le_2', source: 'le_2', target: 'le_3' },
      { id: 'e_le_3', source: 'le_3', target: 'le_4', sourceHandle: 'pass' },
      { id: 'e_le_4', source: 'le_3', target: 'le_8', sourceHandle: 'fail' },
      { id: 'e_le_5', source: 'le_4', target: 'le_5' },
      { id: 'e_le_6', source: 'le_5', target: 'le_6', sourceHandle: 'approved' },
      { id: 'e_le_7', source: 'le_5', target: 'le_8', sourceHandle: 'rejected' },
      { id: 'e_le_8', source: 'le_6', target: 'le_7' },
    ],
  },
];
