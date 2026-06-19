import { useEffect, useState } from 'react';
import { ReactFlowProvider } from 'reactflow';
import { WorkflowCanvas } from './components/WorkflowCanvas';
import { LoginPage } from './pages/LoginPage';
import { AdminPanel } from './pages/AdminPanel';
import { useAuthStore } from './store/authStore';
import { authApi } from './services/api';
import { Loader2 } from 'lucide-react';

function App() {
  const { user, token, setAuth, logout, activeView } = useAuthStore();
  const [bootstrapping, setBootstrapping] = useState(true);

  useEffect(() => {
    if (!token) {
      setBootstrapping(false);
      return;
    }
    authApi.getMe()
      .then(me => setAuth(me, token))
      .catch(() => logout())
      .finally(() => setBootstrapping(false));
  // Run once on mount only
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (bootstrapping) {
    return (
      <div className="w-full h-screen flex items-center justify-center bg-slate-900">
        <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  if (activeView === 'admin' && user.role === 'admin') {
    return <AdminPanel />;
  }

  return (
    <div className="w-full h-screen">
      <ReactFlowProvider>
        <WorkflowCanvas />
      </ReactFlowProvider>
    </div>
  );
}

export default App;
