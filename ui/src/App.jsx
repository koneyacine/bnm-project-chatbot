import { Navigate, Route, Routes } from 'react-router-dom'
import AdminDashboard from './pages/AdminDashboard'
import BackOfficeDashboard from './pages/BackOfficeDashboard'
import BackOfficeLoginPage from './pages/BackOfficeLoginPage'
import ClientChatPage from './pages/ClientChatPage'
import ClientEntryPage from './pages/ClientEntryPage'
import HomePage from './pages/HomePage'

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('bnm_token')
  return token ? children : <Navigate to="/backoffice" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/client" element={<ClientEntryPage />} />
      <Route path="/client/chat" element={<ClientChatPage />} />
      <Route path="/backoffice" element={<BackOfficeLoginPage />} />
      <Route path="/backoffice/dashboard" element={
        <ProtectedRoute>
          <BackOfficeDashboard />
        </ProtectedRoute>
      } />
      <Route path="/backoffice/admin" element={
        <ProtectedRoute>
          <AdminDashboard />
        </ProtectedRoute>
      } />
    </Routes>
  )
}
