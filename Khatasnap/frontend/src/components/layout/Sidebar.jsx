import React, { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { FileText, Calculator, Package, BrainCircuit, LayoutDashboard, ClipboardCheck } from 'lucide-react';
import axios from 'axios';
import { getLearningStats } from '../../api/calculator';

export default function Sidebar() {
  const [health, setHealth] = useState({ orchestrator: true, ocr: true, voice: true, sre: true, inventory: true });
  const [learningStats, setLearningStats] = useState({ total: 0, learned: 0 });

  useEffect(() => {
    const poll = async () => {
      try {
        const check = async (port) => {
          try {
            await axios.get(`http://localhost:${port}/health`, { timeout: 2000 });
            return true;
          } catch { return false; }
        };
        const [orchestrator, ocr, voice, sre, inventory] = await Promise.all([
          check(8000), check(8001), check(8002), check(8003), check(8004)
        ]);
        setHealth({ orchestrator, ocr, voice, sre, inventory });
        
        getLearningStats().then(setLearningStats).catch(() => {});
      } catch (e) {}
    };
    poll();
    const int = setInterval(poll, 30000);
    return () => clearInterval(int);
  }, []);

  const navItemStyle = ({ isActive }) => ({
    display: 'flex', alignItems: 'center', gap: '12px', height: '40px', padding: '0 12px',
    borderRadius: 'var(--radius-md)', textDecoration: 'none', fontSize: '14px',
    color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
    backgroundColor: isActive ? 'var(--accent-light)' : 'transparent',
    fontWeight: isActive ? '500' : '400',
    transition: 'all 150ms ease'
  });

  return (
    <div style={{ width: '220px', background: 'var(--surface)', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', height: '100vh', flexShrink: 0 }}>
      <div style={{ padding: '24px 20px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: '18px', fontWeight: 'bold', color: 'var(--accent)' }}>KhataSnap</div>
        <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Smart Kirana OS</div>
      </div>
      
      <nav style={{ flex: 1, padding: '16px 12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <NavLink to="/ocr" style={navItemStyle}><FileText size={18} /> Bills (OCR)</NavLink>
        <NavLink to="/calculator" style={navItemStyle}><Calculator size={18} /> Calculator</NavLink>
        <NavLink to="/inventory" style={navItemStyle}><Package size={18} /> Inventory</NavLink>
        <NavLink to="/dashboard" style={navItemStyle}><LayoutDashboard size={18} /> Dashboard</NavLink>

      </nav>

      <div style={{ padding: '16px 20px', borderTop: '1px solid var(--border)', fontSize: '12px', color: 'var(--text-secondary)' }}>
        <div style={{ marginBottom: '12px' }}>
           <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: '500', color: 'var(--accent)', marginBottom: '4px' }}>
              <BrainCircuit size={14} /> Pattern Engine
           </div>
           <div>{learningStats.learned} of {learningStats.total} prices assigned intelligently.</div>
           <div style={{ height: '4px', background: 'var(--surface-2)', borderRadius: '2px', marginTop: '6px', overflow: 'hidden' }}>
              <div style={{ height: '100%', background: 'var(--accent)', width: `${learningStats.total ? (learningStats.learned/learningStats.total)*100 : 0}%`, transition: 'width 1s' }} />
           </div>
        </div>
        
        <div style={{ marginBottom: '8px', fontWeight: '500', marginTop: '16px' }}>System Status</div>
        {Object.entries(health).map(([service, isUp]) => (
          <div key={service} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: isUp ? 'var(--success)' : 'var(--danger)' }} />
            <span style={{ textTransform: 'capitalize' }}>{service}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
