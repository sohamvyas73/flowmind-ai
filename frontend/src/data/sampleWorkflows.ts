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

  // ── Data pipeline examples (load the example files first: Data page → "Load example data") ──
  {
    name: 'Data: Tidy up messy contacts',
    description: 'Trim spaces, lowercase emails, drop blanks and duplicates, then count people per city. Needs messy_contacts.csv.',
    nodes: [
      { id: 'dc_1', type: 'loadDataNode', position: { x: 60, y: 160 },
        data: { label: 'Messy contacts', source: 'file', fileName: 'messy_contacts.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'dc_2', type: 'cleanDataNode', position: { x: 300, y: 160 },
        data: { label: 'Tidy up', trimAll: true, removeDuplicates: true, dropMissing: ['name'],
                fillMissing: [{ column: 'city', value: 'Unknown' }], rename: [], keepColumns: [],
                textCase: { columns: ['email'], mode: 'lower' } } },
      { id: 'dc_3', type: 'summariseDataNode', position: { x: 540, y: 160 },
        data: { label: 'People per city', groupBy: ['city'], aggregations: [{ column: '*', fn: 'count', as: 'people' }] } },
    ],
    edges: [
      { id: 'dc_e1', source: 'dc_1', target: 'dc_2' },
      { id: 'dc_e2', source: 'dc_2', target: 'dc_3' },
    ],
  },
  {
    name: 'Data: Sales by region',
    description: 'Total revenue and units per region from the daily sales file. Needs sales.csv.',
    nodes: [
      { id: 'ds_1', type: 'loadDataNode', position: { x: 60, y: 160 },
        data: { label: 'Daily sales', source: 'file', fileName: 'sales.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'ds_2', type: 'summariseDataNode', position: { x: 300, y: 160 },
        data: { label: 'Revenue by region', groupBy: ['region'], aggregations: [
          { column: 'revenue', fn: 'sum', as: 'total_revenue' }, { column: 'units', fn: 'sum', as: 'total_units' } ] } },
    ],
    edges: [{ id: 'ds_e1', source: 'ds_1', target: 'ds_2' }],
  },
  {
    name: 'Data: Orders + customers (join)',
    description: 'Combine two tables on customer_id, then total spend per customer tier. Needs orders.csv and customers.csv.',
    nodes: [
      { id: 'dj_1', type: 'loadDataNode', position: { x: 60, y: 80 },
        data: { label: 'Orders', source: 'file', fileName: 'orders.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'dj_2', type: 'loadDataNode', position: { x: 60, y: 260 },
        data: { label: 'Customers', source: 'file', fileName: 'customers.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'dj_3', type: 'combineDataNode', position: { x: 300, y: 170 },
        data: { label: 'Orders with customer', joinType: 'inner', keys: [{ left: 'customer_id', right: 'customer_id' }], swap: false } },
      { id: 'dj_4', type: 'sqlNode', position: { x: 540, y: 170 },
        data: { label: 'Spend per tier', query:
          "SELECT tier,\n       count(*) AS orders,\n       round(sum(quantity * unit_price), 2) AS revenue\nFROM input\nWHERE status <> 'cancelled'\nGROUP BY tier\nORDER BY revenue DESC" } },
    ],
    edges: [
      { id: 'dj_e1', source: 'dj_1', target: 'dj_3' },
      { id: 'dj_e2', source: 'dj_2', target: 'dj_3' },
      { id: 'dj_e3', source: 'dj_3', target: 'dj_4' },
    ],
  },
  {
    name: 'Data: Top products (SQL)',
    description: 'A single SQL query for engineers: best-selling products by revenue. Needs orders.csv.',
    nodes: [
      { id: 'dq_1', type: 'loadDataNode', position: { x: 60, y: 160 },
        data: { label: 'Orders', source: 'file', fileName: 'orders.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'dq_2', type: 'sqlNode', position: { x: 300, y: 160 },
        data: { label: 'Top products', query:
          "SELECT product,\n       sum(quantity) AS units,\n       sum(quantity * unit_price) AS revenue\nFROM orders\nWHERE status = 'delivered'\nGROUP BY product\nORDER BY revenue DESC\nLIMIT 5" } },
    ],
    edges: [{ id: 'dq_e1', source: 'dq_1', target: 'dq_2' }],
  },
  {
    name: 'Data: Quality gate on dirty orders',
    description: 'A Quality Check that finds duplicates, bad quantities and typos before anything else runs. Needs orders_dirty.csv. Preview it, then switch "When a check fails" to Stop.',
    nodes: [
      { id: 'dg_1', type: 'loadDataNode', position: { x: 60, y: 160 },
        data: { label: 'Dirty orders', source: 'file', fileName: 'orders_dirty.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'dg_2', type: 'qualityGateNode', position: { x: 300, y: 160 },
        data: { label: 'Order checks', onFail: 'warn', rules: [
          { type: 'unique', columns: ['order_id'] },
          { type: 'not_null', columns: ['customer_id', 'unit_price'] },
          { type: 'range', column: 'quantity', min: 1, max: 100 },
          { type: 'allowed_values', column: 'status', values: ['delivered', 'shipped', 'cancelled'] },
          { type: 'regex', column: 'order_date', pattern: '^\\d{4}-\\d{2}-\\d{2}$' },
        ] } },
      { id: 'dg_3', type: 'summariseDataNode', position: { x: 540, y: 160 },
        data: { label: 'Orders by status', groupBy: ['status'], aggregations: [{ column: '*', fn: 'count', as: 'orders' }] } },
    ],
    edges: [
      { id: 'dg_e1', source: 'dg_1', target: 'dg_2' },
      { id: 'dg_e2', source: 'dg_2', target: 'dg_3' },
    ],
  },
  {
    name: 'Data: Protect personal data',
    description: 'Hash emails and mask names before sharing a table. Needs customers.csv.',
    nodes: [
      { id: 'dp_1', type: 'loadDataNode', position: { x: 60, y: 160 },
        data: { label: 'Customers', source: 'file', fileName: 'customers.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'dp_2', type: 'cleanDataNode', position: { x: 300, y: 160 },
        data: { label: 'Protect', trimAll: true, removeDuplicates: false, dropMissing: [], fillMissing: [], rename: [], keepColumns: [],
                protect: [{ column: 'email', method: 'hash' }, { column: 'name', method: 'mask' }], hashSalt: '' } },
      { id: 'dp_3', type: 'sqlNode', position: { x: 540, y: 160 },
        data: { label: 'Share-safe table', query: 'SELECT customer_id, name, left(email, 12) AS contact_hash, city, tier\nFROM input' } },
    ],
    edges: [
      { id: 'dp_e1', source: 'dp_1', target: 'dp_2' },
      { id: 'dp_e2', source: 'dp_2', target: 'dp_3' },
    ],
  },
  {
    name: 'RAG: Index the help centre',
    description: 'Make the example help-centre documents searchable. Set up Retrieval first (nothing is chosen for you), then load the example docs.',
    nodes: [
      { id: 'ri_1', type: 'indexDocsNode', position: { x: 60, y: 160 },
        data: { label: 'Index help centre', collection: 'help', source: 'files', fileNames: [], textColumn: '', sourceColumn: '', chunkSize: 400, overlap: 50, removeMissing: false } },
    ],
    edges: [],
  },
  {
    name: 'RAG: Ask the help centre',
    description: 'Ask a question and get an answer written only from your documents, with citations. Needs the help collection indexed.',
    nodes: [
      { id: 'ra_1', type: 'inputNode', position: { x: 60, y: 160 },
        data: { label: 'Question', description: 'What the customer asks', fields: [{ id: 'ra_f1', name: 'question', type: 'text' }] } },
      { id: 'ra_2', type: 'ragAnswerNode', position: { x: 320, y: 160 },
        data: { label: 'Answer from docs', collection: 'help', question: '{{question}}', topK: 3, minScore: 0, instructions: 'Answer in one or two sentences.', noAnswerText: 'I could not find this in your documents.', temperature: 0.1 } },
      { id: 'ra_3', type: 'outputNode', position: { x: 600, y: 160 }, data: { label: 'Answer', outputType: 'api' } },
    ],
    edges: [
      { id: 'ra_e1', source: 'ra_1', target: 'ra_2' },
      { id: 'ra_e2', source: 'ra_2', target: 'ra_3' },
    ],
  },
  {
    name: 'RAG: Find passages (no AI)',
    description: 'Search only: returns the best-matching passages and their scores. Free of AI costs.',
    nodes: [
      { id: 'rf_1', type: 'inputNode', position: { x: 60, y: 160 },
        data: { label: 'Question', description: 'What to look for', fields: [{ id: 'rf_f1', name: 'question', type: 'text' }] } },
      { id: 'rf_2', type: 'retrieveNode', position: { x: 320, y: 160 },
        data: { label: 'Find passages', collection: 'help', query: '{{question}}', topK: 3, minScore: 0 } },
      { id: 'rf_3', type: 'outputNode', position: { x: 600, y: 160 }, data: { label: 'Passages', outputType: 'api' } },
    ],
    edges: [
      { id: 'rf_e1', source: 'rf_1', target: 'rf_2' },
      { id: 'rf_e2', source: 'rf_2', target: 'rf_3' },
    ],
  },
  {
    name: 'ML: Score customers for churn',
    description: 'Send every customer to your model and count the predictions. Needs a model endpoint connection (see the Models page) and churn_customers.csv.',
    nodes: [
      { id: 'ms_1', type: 'loadDataNode', position: { x: 60, y: 160 }, data: { label: 'Customers', source: 'file', fileName: 'churn_customers.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'ms_2', type: 'batchScoreNode', position: { x: 320, y: 160 }, data: { label: 'Score churn', connectionId: '', features: ['tenure_months', 'monthly_spend', 'support_tickets'], outputColumn: 'prediction', batchSize: 200, maxRows: '' } },
      { id: 'ms_3', type: 'summariseDataNode', position: { x: 580, y: 160 }, data: { label: 'Predictions', groupBy: ['prediction'], aggregations: [{ column: '*', fn: 'count', as: 'customers' }] } },
    ],
    edges: [{ id: 'ms_e1', source: 'ms_1', target: 'ms_2' }, { id: 'ms_e2', source: 'ms_2', target: 'ms_3' }],
  },
  {
    name: 'ML: Will this customer churn? (one record)',
    description: 'Type in one customer and get a prediction from your model endpoint.',
    nodes: [
      { id: 'mp_1', type: 'inputNode', position: { x: 60, y: 160 }, data: { label: 'Customer', description: 'What we know', fields: [
        { id: 'mp_f1', name: 'tenure_months', type: 'number' }, { id: 'mp_f2', name: 'monthly_spend', type: 'number' }, { id: 'mp_f3', name: 'support_tickets', type: 'number' }] } },
      { id: 'mp_2', type: 'predictNode', position: { x: 320, y: 160 }, data: { label: 'Churn?', connectionId: '', features: ['tenure_months', 'monthly_spend', 'support_tickets'], autoNumbers: true } },
      { id: 'mp_3', type: 'outputNode', position: { x: 580, y: 160 }, data: { label: 'Prediction', outputType: 'api' } },
    ],
    edges: [{ id: 'mp_e1', source: 'mp_1', target: 'mp_2' }, { id: 'mp_e2', source: 'mp_2', target: 'mp_3' }],
  },
  {
    name: 'ML: Watch for data drift',
    description: "Compare this week's customers with the training data and stop if they have changed. Needs churn_reference.csv and churn_this_week.csv.",
    nodes: [
      { id: 'md_1', type: 'loadDataNode', position: { x: 60, y: 160 }, data: { label: 'This week', source: 'file', fileName: 'churn_this_week.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'md_2', type: 'driftCheckNode', position: { x: 320, y: 160 }, data: { label: 'Drift check', referenceFile: 'churn_reference.csv', columns: [], warnAt: 0.1, alertAt: 0.25, onDrift: 'stop' } },
    ],
    edges: [{ id: 'md_e1', source: 'md_1', target: 'md_2' }],
  },
  {
    name: 'ML: Score and check accuracy',
    description: 'Score customers whose real outcome is known, then record how often the model was right. Needs a model endpoint connection.',
    nodes: [
      { id: 'mf_1', type: 'loadDataNode', position: { x: 60, y: 160 }, data: { label: 'Customers', source: 'file', fileName: 'churn_customers.csv', connectionId: '', schema: 'public', table: '', maxRows: '' } },
      { id: 'mf_2', type: 'batchScoreNode', position: { x: 320, y: 160 }, data: { label: 'Score churn', connectionId: '', features: ['tenure_months', 'monthly_spend', 'support_tickets'], outputColumn: 'prediction', batchSize: 200, maxRows: '' } },
      { id: 'mf_3', type: 'feedbackNode', position: { x: 580, y: 160 }, data: { label: 'How often right?', modelName: 'churn-model', taskType: 'classification', predictionColumn: 'prediction', actualColumn: 'churned', threshold: 0.8, onFail: 'warn' } },
    ],
    edges: [{ id: 'mf_e1', source: 'mf_1', target: 'mf_2' }, { id: 'mf_e2', source: 'mf_2', target: 'mf_3' }],
  },
  {
    name: 'ML: Promote a better model',
    description: 'Move the "champion" alias to the newest version only if its accuracy is at least 0.85 and beats the current champion. Needs a read & write MLflow connection.',
    nodes: [
      { id: 'mr_1', type: 'registryPromoteNode', position: { x: 60, y: 160 }, data: { label: 'Promote to champion', connectionId: '', modelName: 'churn-model', version: 'latest', alias: 'champion',
        gates: [{ metric: 'accuracy', op: '>=', value: 0.85 }], beatCurrent: true, compareMetric: 'accuracy', higherIsBetter: true, onFail: 'stop' } },
    ],
    edges: [],
  },
  {
    name: 'Warehouse: Revenue by region (data stays put)',
    description: 'Summarise a warehouse table without copying it anywhere: the work runs inside your warehouse. Needs a warehouse connection with the example tables (Connections page → Load example tables).',
    nodes: [
      { id: 'wr_1', type: 'loadDataNode', position: { x: 60, y: 160 }, data: { label: 'Sales (in warehouse)', source: 'connection', connectionId: '', schema: '', table: 'sales', runOn: 'warehouse', columns: [], maxRows: '' } },
      { id: 'wr_2', type: 'summariseDataNode', position: { x: 340, y: 160 }, data: { label: 'Revenue by region', groupBy: ['region'], aggregations: [{ column: 'revenue', fn: 'sum', as: 'total_revenue' }, { column: 'units', fn: 'sum', as: 'total_units' }] } },
    ],
    edges: [{ id: 'wr_e1', source: 'wr_1', target: 'wr_2' }],
  },
  {
    name: 'Warehouse: Join and summarise in place',
    description: 'Join orders to customers and total spend per tier — entirely inside your warehouse.',
    nodes: [
      { id: 'wj_1', type: 'loadDataNode', position: { x: 60, y: 80 }, data: { label: 'Orders', source: 'connection', connectionId: '', schema: '', table: 'orders', runOn: 'warehouse', columns: [], maxRows: '' } },
      { id: 'wj_2', type: 'loadDataNode', position: { x: 60, y: 260 }, data: { label: 'Customers', source: 'connection', connectionId: '', schema: '', table: 'customers', runOn: 'warehouse', columns: [], maxRows: '' } },
      { id: 'wj_3', type: 'combineDataNode', position: { x: 340, y: 160 }, data: { label: 'Orders + customers', joinType: 'inner', keys: [{ left: 'customer_id', right: 'customer_id' }], swap: false } },
      { id: 'wj_4', type: 'summariseDataNode', position: { x: 620, y: 160 }, data: { label: 'Spend by tier', groupBy: ['tier'], aggregations: [{ column: 'quantity', fn: 'sum', as: 'units' }, { column: '*', fn: 'count', as: 'orders' }] } },
    ],
    edges: [{ id: 'wj_e1', source: 'wj_1', target: 'wj_3' }, { id: 'wj_e2', source: 'wj_2', target: 'wj_3' }, { id: 'wj_e3', source: 'wj_3', target: 'wj_4' }],
  },
  {
    name: 'Warehouse: Summarise, then bring the result in',
    description: 'Do the heavy lifting in the warehouse, then Pull only the small result into FlowMind and check its quality.',
    nodes: [
      { id: 'wp_1', type: 'loadDataNode', position: { x: 40, y: 160 }, data: { label: 'Sales (in warehouse)', source: 'connection', connectionId: '', schema: '', table: 'sales', runOn: 'warehouse', columns: [], maxRows: '' } },
      { id: 'wp_2', type: 'summariseDataNode', position: { x: 300, y: 160 }, data: { label: 'Revenue by region', groupBy: ['region'], aggregations: [{ column: 'revenue', fn: 'sum', as: 'total_revenue' }] } },
      { id: 'wp_3', type: 'pullDataNode', position: { x: 560, y: 160 }, data: { label: 'Bring into FlowMind', maxRows: '' } },
      { id: 'wp_4', type: 'qualityGateNode', position: { x: 820, y: 160 }, data: { label: 'Check the result', onFail: 'stop', rules: [{ type: 'not_null', columns: ['region', 'total_revenue'] }] } },
    ],
    edges: [{ id: 'wp_e1', source: 'wp_1', target: 'wp_2' }, { id: 'wp_e2', source: 'wp_2', target: 'wp_3' }, { id: 'wp_e3', source: 'wp_3', target: 'wp_4' }],
  },
  {
    name: 'Warehouse: Save a summary table',
    description: 'Create a new table in your warehouse from a summary — the data never leaves it. Needs a Read & write connection; pick a dedicated schema.',
    nodes: [
      { id: 'ws_1', type: 'loadDataNode', position: { x: 40, y: 160 }, data: { label: 'Sales (in warehouse)', source: 'connection', connectionId: '', schema: '', table: 'sales', runOn: 'warehouse', columns: [], maxRows: '' } },
      { id: 'ws_2', type: 'summariseDataNode', position: { x: 300, y: 160 }, data: { label: 'Revenue by region', groupBy: ['region'], aggregations: [{ column: 'revenue', fn: 'sum', as: 'total_revenue' }] } },
      { id: 'ws_3', type: 'writeWarehouseNode', position: { x: 560, y: 160 }, data: { label: 'Save summary', connectionId: '', schema: '', table: 'revenue_by_region', mode: '' } },
    ],
    edges: [{ id: 'ws_e1', source: 'ws_1', target: 'ws_2' }, { id: 'ws_e2', source: 'ws_2', target: 'ws_3' }],
  },
];
