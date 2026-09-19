import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { PublicOnly, RequireAuth } from './components/RequireAuth'
import { CatalogUploadPage } from './pages/CatalogUploadPage'
import { ChatPage } from './pages/ChatPage'
import { ConnectPage } from './pages/ConnectPage'
import { ForgotPasswordPlaceholder } from './pages/ForgotPasswordPlaceholder'
import { HomePage } from './pages/HomePage'
import { InvoiceDetailPage, InvoicesPage } from './pages/InvoicesPage'
import { LandingPage } from './pages/LandingPage'
import { LoginPage } from './pages/LoginPage'
import { ProfilePage } from './pages/ProfilePage'
import { SignupPage } from './pages/SignupPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <PublicOnly>
              <LandingPage />
            </PublicOnly>
          }
        />
        <Route
          path="/login"
          element={
            <PublicOnly>
              <LoginPage />
            </PublicOnly>
          }
        />
        <Route
          path="/signup"
          element={
            <PublicOnly>
              <SignupPage />
            </PublicOnly>
          }
        />
        <Route path="/forgot-password" element={<ForgotPasswordPlaceholder />} />
        <Route path="/connect/:merchantId" element={<ConnectPage />} />
        <Route
          path="/home"
          element={
            <RequireAuth>
              <HomePage />
            </RequireAuth>
          }
        />
        <Route
          path="/home/catalog-upload"
          element={
            <RequireAuth>
              <CatalogUploadPage />
            </RequireAuth>
          }
        />
        <Route
          path="/home/chat"
          element={
            <RequireAuth>
              <ChatPage />
            </RequireAuth>
          }
        />
        <Route
          path="/home/invoices"
          element={
            <RequireAuth>
              <InvoicesPage />
            </RequireAuth>
          }
        />
        <Route
          path="/home/invoices/:invoiceId"
          element={
            <RequireAuth>
              <InvoiceDetailPage />
            </RequireAuth>
          }
        />
        <Route
          path="/home/profile"
          element={
            <RequireAuth>
              <ProfilePage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
