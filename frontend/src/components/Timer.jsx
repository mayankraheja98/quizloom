import { useEffect, useRef, useState } from "react";

/**
 * Countdown timer.
 * Props:
 *   totalSeconds  — starting value
 *   onExpire      — called when timer hits 0
 */
export default function Timer({ totalSeconds, onExpire }) {
  const [remaining, setRemaining] = useState(totalSeconds);
  const expiredRef = useRef(false);

  useEffect(() => {
    if (remaining <= 0) {
      if (!expiredRef.current) {
        expiredRef.current = true;
        onExpire?.();
      }
      return;
    }
    const id = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(id);
  }, [remaining, onExpire]);

  const mins = Math.floor(remaining / 60)
    .toString()
    .padStart(2, "0");
  const secs = (remaining % 60).toString().padStart(2, "0");

  const urgent = remaining <= 60;

  return (
    <div
      className={`text-2xl font-mono font-bold px-4 py-2 rounded-lg ${
        urgent ? "bg-red-100 text-red-700 animate-pulse" : "bg-indigo-100 text-indigo-700"
      }`}
    >
      {mins}:{secs}
    </div>
  );
}
