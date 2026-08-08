/**
 * CallContext — manages all DAWA call state, polling, and history.
 *
 * Persists apiBaseUrl, adminToken, and medicationName in AsyncStorage.
 * Polls GET /api/test-call/status every 3 s while a call is active.
 *
 * Status resolution strategy (most-advanced wins):
 *   1. Boolean progress flags (dialing / ringing / answered / completed / failed)
 *      set by the _normalise_session() layer in the DAWA backend.
 *   2. String `status` field fallback — covers any Uplift response that provides
 *      state as a string rather than individual boolean flags.
 *
 * History reconciliation:
 *   The backend call-log always records status as "dispatched" (P0-B limitation).
 *   We maintain a local statusOverrides map keyed by callId so that completed /
 *   failed calls show their real outcome in the history list without requiring
 *   a backend change.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

// ─── Types ────────────────────────────────────────────────────────────────────

export type CallPhase =
  | 'idle'
  | 'dispatching'
  | 'dispatched'
  | 'dialing'
  | 'ringing'
  | 'answered'
  | 'completed'
  | 'failed';

export interface CallLogEntry {
  logId: string;
  callId: string;
  medication: string;
  dispatchedAt: string;
  status: string;
}

export interface CallStatusEntry {
  sessionId?: string;
  callId?: string;
  /** Boolean progress flags set by the DAWA normalise_session() layer */
  dispatched?: boolean;
  dialing?: boolean;
  ringing?: boolean;
  answered?: boolean;
  completed?: boolean;
  failed?: boolean;
  failureReason?: string | null;
  /**
   * String status field — present when Uplift encodes state as a single string
   * (e.g. "completed", "failed", "answered") rather than individual booleans.
   * Used as a fallback when no boolean flag is set.
   */
  status?: string;
  startedAt?: string | null;
  endedAt?: string | null;
  [key: string]: unknown;
}

interface CallContextValue {
  // Config
  apiBaseUrl: string;
  adminToken: string;
  medicationName: string;
  setConfig: (params: {
    apiBaseUrl?: string;
    adminToken?: string;
    medicationName?: string;
  }) => Promise<void>;

  // Active call
  callPhase: CallPhase;
  activeCallId: string | null;
  failureReason: string | null;
  dispatchCall: () => Promise<void>;
  dispatchError: string | null;

  // History (with local status overrides applied)
  callHistory: CallLogEntry[];
  isLoadingHistory: boolean;
  refreshHistory: () => Promise<void>;

  // Setup state
  isConfigured: boolean;
}

// ─── Storage keys ─────────────────────────────────────────────────────────────

const KEY_API_URL = 'dawa_api_url';
const KEY_TOKEN = 'dawa_admin_token';
const KEY_MED = 'dawa_medication';

// ─── Phase derivation helpers ─────────────────────────────────────────────────

/**
 * Map a raw status string to a CallPhase.
 * Matches common Uplift status strings and their variations.
 */
function phaseFromString(raw: string): CallPhase | null {
  const s = raw.toLowerCase().trim();
  if (s.includes('fail') || s === 'error') return 'failed';
  if (s.includes('complet') || s === 'ended' || s === 'done') return 'completed';
  if (s.includes('answer') || s === 'active' || s === 'in_progress') return 'answered';
  if (s.includes('ring')) return 'ringing';
  if (s.includes('dial') || s === 'connecting') return 'dialing';
  if (s.includes('dispatch') || s === 'queued' || s === 'initiated') return 'dispatched';
  return null;
}

/**
 * Derive the most-advanced CallPhase from a status entry.
 *
 * Priority order:
 *   1. Boolean flags (most reliable — set by the DAWA normalise_session layer)
 *   2. String `status` field fallback
 *   3. Default: 'dispatched'
 */
function derivePhase(entry: CallStatusEntry): CallPhase {
  // Boolean flags — check most-advanced first
  if (entry.failed) return 'failed';
  if (entry.completed) return 'completed';
  if (entry.answered) return 'answered';
  if (entry.ringing) return 'ringing';
  if (entry.dialing) return 'dialing';
  if (entry.dispatched) return 'dispatched';

  // String fallback
  if (entry.status) {
    const fromStr = phaseFromString(entry.status);
    if (fromStr) return fromStr;
  }

  return 'dispatched';
}

// ─── Context ──────────────────────────────────────────────────────────────────

const CallContext = createContext<CallContextValue | null>(null);

export function CallProvider({ children }: { children: React.ReactNode }) {
  const [apiBaseUrl, setApiBaseUrl] = useState('');
  const [adminToken, setAdminToken] = useState('');
  const [medicationName, setMedicationName] = useState('میٹفارمن');
  const [configLoaded, setConfigLoaded] = useState(false);

  const [callPhase, setCallPhase] = useState<CallPhase>('idle');
  const [activeCallId, setActiveCallId] = useState<string | null>(null);
  const [failureReason, setFailureReason] = useState<string | null>(null);
  const [dispatchError, setDispatchError] = useState<string | null>(null);

  const [rawHistory, setRawHistory] = useState<CallLogEntry[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);

  /**
   * Local status overrides keyed by callId.
   * Populated when polling detects a terminal state so that history rows
   * show the real outcome instead of the backend's static "dispatched".
   */
  const [statusOverrides, setStatusOverrides] = useState<Record<string, string>>({});

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── Derived history with overrides applied ────────────────────────────────

  const callHistory: CallLogEntry[] = rawHistory.map((entry) => {
    const override = statusOverrides[entry.callId];
    return override ? { ...entry, status: override } : entry;
  });

  // ─── Load config from storage ──────────────────────────────────────────────

  useEffect(() => {
    (async () => {
      try {
        const [url, token, med] = await AsyncStorage.multiGet([
          KEY_API_URL,
          KEY_TOKEN,
          KEY_MED,
        ]);
        if (url[1]) setApiBaseUrl(url[1]);
        if (token[1]) setAdminToken(token[1]);
        if (med[1]) setMedicationName(med[1]);
      } catch (_) {
        // ignore storage errors
      } finally {
        setConfigLoaded(true);
      }
    })();
  }, []);

  const setConfig = useCallback(
    async (params: {
      apiBaseUrl?: string;
      adminToken?: string;
      medicationName?: string;
    }) => {
      const pairs: [string, string][] = [];
      if (params.apiBaseUrl !== undefined) {
        setApiBaseUrl(params.apiBaseUrl);
        pairs.push([KEY_API_URL, params.apiBaseUrl]);
      }
      if (params.adminToken !== undefined) {
        setAdminToken(params.adminToken);
        pairs.push([KEY_TOKEN, params.adminToken]);
      }
      if (params.medicationName !== undefined) {
        setMedicationName(params.medicationName);
        pairs.push([KEY_MED, params.medicationName]);
      }
      if (pairs.length > 0) {
        await AsyncStorage.multiSet(pairs);
      }
    },
    [],
  );

  const isConfigured = apiBaseUrl.length > 0 && adminToken.length > 0;

  // ─── History ───────────────────────────────────────────────────────────────

  const refreshHistory = useCallback(async () => {
    if (!apiBaseUrl || !adminToken) return;
    setIsLoadingHistory(true);
    try {
      const res = await fetch(`${apiBaseUrl}/api/call-log`, {
        headers: { 'X-Admin-Token': adminToken },
      });
      if (res.ok) {
        const data = await res.json();
        setRawHistory(Array.isArray(data) ? data : []);
      }
    } catch (_) {
      // keep existing list on network error
    } finally {
      setIsLoadingHistory(false);
    }
  }, [apiBaseUrl, adminToken]);

  // ─── Polling ───────────────────────────────────────────────────────────────

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const pollStatus = useCallback(
    async (callId: string) => {
      if (!apiBaseUrl) return;
      try {
        const res = await fetch(`${apiBaseUrl}/api/test-call/status?limit=20`);
        if (!res.ok) return;
        const data: CallStatusEntry[] = await res.json();
        if (!Array.isArray(data)) return;

        // Find session by callId; fall back to the first entry when only one
        // active call is in flight (callId may be empty if Uplift didn't return one)
        const entry =
          data.find((d) => d.callId === callId && callId !== '') ??
          (data.length === 1 ? data[0] : undefined);
        if (!entry) return;

        const phase = derivePhase(entry);
        setCallPhase(phase);

        if (phase === 'failed' && entry.failureReason) {
          setFailureReason(String(entry.failureReason));
        }

        if (phase === 'completed' || phase === 'failed') {
          stopPolling();

          // Record the real outcome so history rows show the actual status
          const resolvedCallId = entry.callId ?? callId;
          if (resolvedCallId) {
            setStatusOverrides((prev) => ({
              ...prev,
              [resolvedCallId]: phase,
            }));
          }

          // Refresh backend history after a short delay (log may update after call ends)
          setTimeout(() => refreshHistory(), 1500);
        }
      } catch (_) {
        // ignore transient poll errors; next tick will retry
      }
    },
    [apiBaseUrl, stopPolling, refreshHistory],
  );

  const startPolling = useCallback(
    (callId: string) => {
      stopPolling();
      // Poll immediately, then every 3 s
      pollStatus(callId);
      pollIntervalRef.current = setInterval(() => {
        pollStatus(callId);
      }, 3000);
    },
    [stopPolling, pollStatus],
  );

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  // ─── Dispatch call ─────────────────────────────────────────────────────────

  const dispatchCall = useCallback(async () => {
    if (!isConfigured || callPhase !== 'idle') return;
    setDispatchError(null);
    setFailureReason(null);
    setCallPhase('dispatching');

    try {
      const res = await fetch(`${apiBaseUrl}/api/test-call`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Token': adminToken,
        },
        body: JSON.stringify({ medication_name: medicationName }),
      });

      if (!res.ok) {
        const body = await res.text();
        let msg = `Server error ${res.status}`;
        try {
          const j = JSON.parse(body);
          if (j.detail) msg = String(j.detail);
        } catch (_) {}
        setDispatchError(msg);
        setCallPhase('idle');
        return;
      }

      const data = await res.json();
      const callId: string = data.callId ?? data.call_id ?? '';
      setActiveCallId(callId);
      setCallPhase('dispatched');
      startPolling(callId);
    } catch (_) {
      setDispatchError('Network error — check your API URL.');
      setCallPhase('idle');
    }
  }, [
    isConfigured,
    callPhase,
    apiBaseUrl,
    adminToken,
    medicationName,
    startPolling,
  ]);

  // ─── Auto-reset after terminal state ──────────────────────────────────────

  const resetCall = useCallback(() => {
    stopPolling();
    setCallPhase('idle');
    setActiveCallId(null);
    setFailureReason(null);
    setDispatchError(null);
  }, [stopPolling]);

  useEffect(() => {
    if (callPhase === 'completed' || callPhase === 'failed') {
      const t = setTimeout(resetCall, 8000);
      return () => clearTimeout(t);
    }
  }, [callPhase, resetCall]);

  // ─── Provider ──────────────────────────────────────────────────────────────

  if (!configLoaded) return null;

  return (
    <CallContext.Provider
      value={{
        apiBaseUrl,
        adminToken,
        medicationName,
        setConfig,
        callPhase,
        activeCallId,
        failureReason,
        dispatchCall,
        dispatchError,
        callHistory,
        isLoadingHistory,
        refreshHistory,
        isConfigured,
      }}
    >
      {children}
    </CallContext.Provider>
  );
}

export function useCall(): CallContextValue {
  const ctx = useContext(CallContext);
  if (!ctx) throw new Error('useCall must be used within CallProvider');
  return ctx;
}
