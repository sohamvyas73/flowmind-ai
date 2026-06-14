import { ReactFlowProvider } from 'reactflow';
import { WorkflowCanvas } from './components/WorkflowCanvas';

function App() {
  return (
    <div className="w-full h-screen">
      <ReactFlowProvider>
        <WorkflowCanvas />
      </ReactFlowProvider>
    </div>
  );
}

export default App;
