import { useEffect, useState } from 'react';
import { ReactFlowProvider } from 'reactflow';
import { WorkflowCanvas } from './components/WorkflowCanvas';
import { LoginPage } from './pages/LoginPage';
import { AdminPanel } from './pages/AdminPanel';
import { ConfigPage } from './pages/ConfigPage';
import { useAuthStore } from './store/authStore';
import { authApi } from './services/api';
import { Loader2, Clock, LogOut } from 'lucide-react';

function PendingApproval() {
  const { user, logout } = useAuthStore();
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-8 text-center">
        <div className="w-14 h-14 bg-amber-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Clock className="w-8 h-8 text-amber-500" />
        </div>
        <h1 className="text-xl font-bold text-gray-900 mb-2">Account Pending Approval</h1>
        <p className="text-gray-500 text-sm mb-1">
          Welcome, <span className="font-medium text-gray-700">{user?.email}</span>!
        </p>
        <p className="text-gray-500 text-sm mb-6">
          Your account has been created successfully. An admin needs to approve your account before
          you can execute workflows. Please check back later.
        </p>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-left mb-6">
          <p className="text-xs font-semibold text-amber-800 mb-1">What happens next?</p>
          <ul className="text-xs text-amber-700 space-y-1">
            <li>• An admin will review and approve your account</li>
            <li>• You'll start with 1,000 credits to run workflows</li>
            <li>• Sign in again after approval to get started</li>
          </ul>
        </div>
        <button
          onClick={logout}
          className="flex items-center gap-2 mx-auto text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Sign out
        </button>
      </div>
    </div>
  );
}

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

  // Non-admin inactive users see the pending approval screen
  if (!user.is_active && user.role !== 'admin') {
    return <PendingApproval />;
  }

  if (activeView === 'admin' && user.role === 'admin') {
    return <AdminPanel />;
  }

  if (activeView === 'config') {
    return <ConfigPage />;
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
