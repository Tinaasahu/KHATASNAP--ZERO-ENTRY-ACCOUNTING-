import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AppShell from './components/layout/AppShell';
import ToastProvider from './components/ui/ToastProvider';
import CalculatorPage from './pages/CalculatorPage';
import OCRPage from './pages/OCRPage';
import InventoryPage from './pages/InventoryPage';
import ShopkeeperDashboardPage from './pages/ShopkeeperDashboardPage';
import ReconciliationPage from './pages/ReconciliationPage';

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route index element={<Navigate to="/calculator" replace />} />
            <Route path="calculator" element={<CalculatorPage />} />
            <Route path="ocr" element={<OCRPage />} />
            <Route path="inventory" element={<InventoryPage />} />
            <Route path="dashboard" element={<ShopkeeperDashboardPage />} />
            <Route path="reconciliation" element={<ReconciliationPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  );
}
