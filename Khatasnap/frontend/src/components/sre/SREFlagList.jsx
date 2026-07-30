import React from 'react';
import { AnimatePresence } from 'framer-motion';
import SREFlagCard from './SREFlagCard';
import EmptyState from '../ui/EmptyState';
import { ShieldCheck } from 'lucide-react';
import Button from '../ui/Button';

export default function SREFlagList({ flags, unassignedFlags = [], onResolve, onAssign, onDismissUnassigned }) {
  const activeFlags = flags.map((f, i) => ({ ...f, originalIndex: i, isPassive: false })).filter(f => !f.resolution || f.resolution === 'pending');
  const activePassive = unassignedFlags.map((f, i) => ({ ...f, isPassive: true }));

  let allFlags = [...activeFlags, ...activePassive];
  allFlags.sort((a, b) => {
    if (a.flag_type === 'OUT_OF_STOCK' && b.flag_type !== 'OUT_OF_STOCK') return -1;
    if (b.flag_type === 'OUT_OF_STOCK' && a.flag_type !== 'OUT_OF_STOCK') return 1;
    if (a.isPassive && !b.isPassive) return 1;
    if (!a.isPassive && b.isPassive) return -1;
    return 0;
  });

  if (allFlags.length === 0) {
    return (
      <EmptyState 
        icon={<ShieldCheck size={32} color="var(--success)" />} 
        message="All entries verified" 
        description="No issues detected or all issues resolved." 
      />
    );
  }

  // Only non-UNRESOLVED active flags can be bulk-accepted
  const bulkFlags = activeFlags.filter(f => f.flag_type !== 'UNRESOLVED_ENTRY');
  const handleResolveAll = () => {
     bulkFlags.forEach(f => onResolve(f.originalIndex, 'accepted'));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {bulkFlags.length >= 2 && (
         <div style={{ marginBottom: '16px' }}>
            <Button variant="secondary" style={{ width: '100%' }} onClick={handleResolveAll}>
               Accept all &amp; save
            </Button>
         </div>
      )}
      <AnimatePresence>
        {allFlags.map(flag => {
          if (flag.isPassive) {
            return (
              <SREFlagCard 
                key={flag.flag_id} 
                flag={flag} 
                autoAcceptSeconds={null}
                onAccept={() => onDismissUnassigned(flag.flag_id)}
                onDismiss={() => onDismissUnassigned(flag.flag_id)}
                onAssign={onAssign}
              />
            );
          } else {
            // Normal active SRE flag (legacy fallback if somehow UNRESOLVED leaks here)
            const autoAccept = flag.flag_type === 'UNRESOLVED_ENTRY'
              ? null
              : (flag.confidence >= 0.5 && flag.confidence < 0.8) ? 6 : null;
            return (
              <SREFlagCard 
                key={flag.flag_id !== undefined ? flag.flag_id : flag.originalIndex} 
                flag={flag} 
                autoAcceptSeconds={autoAccept}
                onAccept={() => onResolve(flag.originalIndex, 'accepted')}
                onCorrect={(val) => onResolve(flag.originalIndex, 'corrected', val)}
                onDismiss={() => onResolve(flag.originalIndex, 'ignored')}
                onAssign={onAssign}
              />
            );
          }
        })}
      </AnimatePresence>
    </div>
  );
}
