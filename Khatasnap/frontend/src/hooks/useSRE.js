import { useState } from 'react';

export function useSRE() {
  const [flags, setFlags] = useState([]);
  const [confirmedData, setConfirmedData] = useState(null);

  const resolveFlag = (index, resolution, correctedValue = null) => {
    setFlags(prev => {
      const newFlags = [...prev];
      newFlags[index] = {
        ...newFlags[index],
        resolution,
        corrected_value: correctedValue
      };
      return newFlags;
    });
  };

  const areAllResolved = () => {
    if (flags.length === 0) return true;
    return flags.every(f => f.resolution === 'accepted' || f.resolution === 'corrected' || f.resolution === 'ignored');
  };

  return { flags, setFlags, resolveFlag, areAllResolved, confirmedData, setConfirmedData };
}
