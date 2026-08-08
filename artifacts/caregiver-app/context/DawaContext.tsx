/**
 * DawaContext — P1+P2 state management for the DAWA caregiver app.
 *
 * P1 endpoints:
 *   GET  /api/dawa/demo          — patient + medications + scheduler state
 *   POST /api/dawa/vmr/resolve   — deterministic medication ID from visual cues
 *   POST /api/dawa/demo-call     — dispatch a verified Uplift call (manual)
 *   GET  /api/dawa/call-status   — dose events + live telephony status
 *
 * P2 endpoints (new):
 *   POST /api/dawa/schedule-demo-call — schedule a proactive call (15–300 s delay)
 *   POST /api/dawa/demo/reset         — clear demo state; preserve patient data
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
import { apiFetch } from '@/lib/api';
import { AUTH_BASE_URL } from '@/lib/config';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Patient {
  id: string;
  name: string;
  preferred_address: string;
  language: string;
  literacy_mode: string;
}

export interface Medication {
  id: string;
  patient_id: string;
  clinical_name: string;
  dosage: string;
  dose_instruction: string;
  food_instruction: string;
  schedule_time: string;
  routine_anchor: string;
  nickname: string | null;
  cues?: Record<string, string>;
}

export interface DoseEvent {
  id: string;
  patientId: string;
  medicationId: string;
  scheduledTime: string;
  callId: string | null;
  callStatus: string;
  adherenceOutcome: string | null;
  retryCount?: number;
  createdAt: string;
  updatedAt: string;
  liveStatus?: {
    status?: string;
    dispatched?: boolean;
    dialing?: boolean;
    ringing?: boolean;
    answered?: boolean;
    completed?: boolean;
    failed?: boolean;
    failureReason?: string | null;
    startedAt?: string | null;
    endedAt?: string | null;
  } | null;
}

export interface ScheduledCallInfo {
  doseEventId: string;
  medicationId: string;
  scheduledTime: string;
  callStatus: string;
  delayRemainingSeconds: number | null;
}

export type VMRStatus = 'UNIQUE' | 'AMBIGUOUS' | 'NO_MATCH';

export interface VMRResult {
  status: VMRStatus;
  medicationId?: string;
  candidateMedicationIds?: string[];
  bestDiscriminator?: string;
}

export type CallPhase =
  | 'idle'
  | 'dispatching'
  | 'dispatched'
  | 'dialing'
  | 'ringing'
  | 'answered'
  | 'completed'
  | 'failed';

interface DawaContextValue {
  // Config
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => Promise<void>;

  // Patient data
  patient: Patient | null;
  medications: Medication[];
  isLoading: boolean;
  loadError: string | null;
  refresh: () => Promise<void>;

  // VMR state
  vmrCues: Record<string, string>;
  addVmrCue: (key: string, value: string) => void;
  clearVmrCues: () => void;
  vmrResult: VMRResult | null;
  vmrLoading: boolean;
  runVmr: () => Promise<void>;

  // Call state (manual)
  callPhase: CallPhase;
  activeCallId: string | null;
  activeDoseEventId: string | null;
  recentDoseEvents: DoseEvent[];
  dispatchCall: (patientId: string, medicationId: string) => Promise<void>;
  callError: string | null;

  // P2 — proactive scheduling
  scheduledCall: ScheduledCallInfo | null;
  countdownSeconds: number | null;
  isScheduling: boolean;
  scheduleDemo: (medicationId: string, delaySeconds: number) => Promise<void>;
  scheduleError: string | null;

  // P2 — demo reset
  isResetting: boolean;
  resetDemo: () => Promise<void>;
  resetError: string | null;
}

// ─── Context ─────────────────────────────────────────────────────────────────

const DawaContext = createContext<DawaContextValue | null>(null);

const STORAGE_KEY_URL = 'dawa_api_url';

/**
 * Default API origin.
 *
 * This MUST resolve to the same origin the Better Auth client is bound to
 * (lib/config.ts AUTH_BASE_URL), otherwise the app would authenticate against
 * one server and read caregiver data from another — the session cookie would
 * never match and every /api/dawa/* call would 401.
 */
function deriveDefaultUrl(): string {
  if (AUTH_BASE_URL) return AUTH_BASE_URL;
  const domain = process.env['EXPO_PUBLIC_DOMAIN'];
  if (domain) return `https://${domain}`;
  return '';
}

// ─── Provider ────────────────────────────────────────────────────────────────

export function DawaProvider({ children }: { children: React.ReactNode }) {
  const [apiBaseUrl, setApiBaseUrlState] = useState<string>(deriveDefaultUrl());
  const [patient, setPatient] = useState<Patient | null>(null);
  const [medications, setMedications] = useState<Medication[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [vmrCues, setVmrCues] = useState<Record<string, string>>({});
  const [vmrResult, setVmrResult] = useState<VMRResult | null>(null);
  const [vmrLoading, setVmrLoading] = useState(false);

  const [callPhase, setCallPhase] = useState<CallPhase>('idle');
  const [activeCallId, setActiveCallId] = useState<string | null>(null);
  const [activeDoseEventId, setActiveDoseEventId] = useState<string | null>(null);
  const [recentDoseEvents, setRecentDoseEvents] = useState<DoseEvent[]>([]);
  const [callError, setCallError] = useState<string | null>(null);

  // P2 scheduling state
  const [scheduledCall, setScheduledCall] = useState<ScheduledCallInfo | null>(null);
  const [countdownSeconds, setCountdownSeconds] = useState<number | null>(null);
  const [isScheduling, setIsScheduling] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  // P2 reset state
  const [isResetting, setIsResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Persist URL ──────────────────────────────────────────────────────────

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY_URL).then((stored) => {
      if (stored && stored.trim()) setApiBaseUrlState(stored.trim());
    });
  }, []);

  const setApiBaseUrl = useCallback(async (url: string) => {
    const trimmed = url.trim();
    setApiBaseUrlState(trimmed);
    await AsyncStorage.setItem(STORAGE_KEY_URL, trimmed);
  }, []);

  // ── Countdown timer ──────────────────────────────────────────────────────

  function startCountdown(seconds: number) {
    stopCountdown();
    setCountdownSeconds(seconds);
    countdownRef.current = setInterval(() => {
      setCountdownSeconds((prev) => {
        if (prev === null || prev <= 1) {
          stopCountdown();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }

  function stopCountdown() {
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
      countdownRef.current = null;
    }
  }

  useEffect(() => () => stopCountdown(), []);

  // ── Load demo data ───────────────────────────────────────────────────────

  const loadDemo = useCallback(async () => {
    if (!apiBaseUrl) return;
    setIsLoading(true);
    setLoadError(null);
    try {
      const res = await apiFetch(apiBaseUrl, '/api/dawa/demo');
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setPatient(data.patient ?? null);
      setMedications(data.medications ?? []);
      setRecentDoseEvents(data.doseEvents ?? []);

      // P2: pick up scheduled call state from demo endpoint
      if (data.nextScheduledCall) {
        const sc: ScheduledCallInfo = data.nextScheduledCall;
        setScheduledCall(sc);
        // Restore cosmetic countdown if delay is still positive
        if (
          typeof sc.delayRemainingSeconds === 'number' &&
          sc.delayRemainingSeconds > 0 &&
          countdownRef.current === null
        ) {
          startCountdown(sc.delayRemainingSeconds);
        }
      } else {
        setScheduledCall(null);
      }
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : 'Failed to connect to DAWA backend');
    } finally {
      setIsLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { loadDemo(); }, [loadDemo]);

  // ── VMR ──────────────────────────────────────────────────────────────────

  const addVmrCue = useCallback((key: string, value: string) => {
    setVmrCues((prev) => ({ ...prev, [key]: value }));
    setVmrResult(null);
  }, []);

  const clearVmrCues = useCallback(() => {
    setVmrCues({});
    setVmrResult(null);
  }, []);

  const runVmr = useCallback(async () => {
    if (!apiBaseUrl || !patient || Object.keys(vmrCues).length === 0) return;
    setVmrLoading(true);
    try {
      const res = await apiFetch(apiBaseUrl, '/api/dawa/vmr/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patientId: patient.id, cues: vmrCues }),
      });
      const data = await res.json();
      setVmrResult(res.ok ? (data as VMRResult) : null);
    } catch {
      setVmrResult(null);
    } finally {
      setVmrLoading(false);
    }
  }, [apiBaseUrl, patient, vmrCues]);

  useEffect(() => {
    if (Object.keys(vmrCues).length > 0 && patient) runVmr();
  }, [vmrCues, patient, runVmr]);

  // ── Poll call status ──────────────────────────────────────────────────────

  const pollCallStatus = useCallback(async () => {
    if (!apiBaseUrl) return;
    try {
      const res = await apiFetch(apiBaseUrl, '/api/dawa/call-status?limit=10');
      if (!res.ok) return;
      const data = await res.json();
      const events: DoseEvent[] = data.doseEvents ?? [];
      setRecentDoseEvents(events);

      // Update callPhase from active manual-dispatch event
      if (activeDoseEventId) {
        const active = events.find((e) => e.id === activeDoseEventId);
        if (active) {
          const phase = derivePhase(active);
          setCallPhase(phase);
          if (active.callId) setActiveCallId(active.callId);
          if (phase === 'completed' || phase === 'failed') stopPolling();
        }
      }

      // Update scheduledCall status when backend transitions it
      if (scheduledCall) {
        const ev = events.find((e) => e.id === scheduledCall.doseEventId);
        if (ev) {
          setScheduledCall((prev) =>
            prev ? { ...prev, callStatus: ev.callStatus } : prev
          );
          // If the scheduled event has moved to a terminal state, stop countdown
          if (['completed', 'failed', 'calling', 'dispatched', 'dialing', 'ringing', 'answered'].includes(ev.callStatus)) {
            stopCountdown();
          }
        }
      }
    } catch {
      // Silently ignore poll failures
    }
  }, [apiBaseUrl, activeDoseEventId, scheduledCall]);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => () => stopPolling(), []);

  // Start polling as long as there's a scheduled or active event
  useEffect(() => {
    const hasActivity =
      (callPhase !== 'idle' && callPhase !== 'completed' && callPhase !== 'failed') ||
      (scheduledCall !== null &&
        !['completed', 'failed'].includes(scheduledCall.callStatus));

    if (hasActivity && !pollRef.current) {
      pollRef.current = setInterval(pollCallStatus, 3000);
    } else if (!hasActivity && pollRef.current) {
      stopPolling();
    }
  }, [callPhase, scheduledCall, pollCallStatus]);

  // ── Dispatch call (manual) ────────────────────────────────────────────────

  const dispatchCall = useCallback(
    async (patientId: string, medicationId: string) => {
      if (!apiBaseUrl) { setCallError('API URL not configured. Open settings.'); return; }
      setCallPhase('dispatching');
      setCallError(null);
      setActiveCallId(null);
      setActiveDoseEventId(null);
      stopPolling();
      try {
        const res = await apiFetch(apiBaseUrl, '/api/dawa/demo-call', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ patientId, medicationId }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail ?? `Call dispatch failed (${res.status})`);
        setActiveCallId(data.callId ?? null);
        setActiveDoseEventId(data.doseEventId ?? null);
        setCallPhase('dispatched');
        pollRef.current = setInterval(pollCallStatus, 3000);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setCallPhase('failed');
        setCallError(msg);
      }
    },
    [apiBaseUrl, pollCallStatus]
  );

  // ── P2: Schedule demo call ────────────────────────────────────────────────

  const scheduleDemo = useCallback(
    async (medicationId: string, delaySeconds: number) => {
      if (!apiBaseUrl) { setScheduleError('API URL not configured. Open settings.'); return; }
      setIsScheduling(true);
      setScheduleError(null);
      try {
        // Resolve the caregiver's own patient rather than assuming a fixed id —
        // every account now has a different one.
        const patientRes = await apiFetch(apiBaseUrl, '/api/dawa/patient');
        const patientBody = await patientRes.json().catch(() => ({}));
        if (!patientRes.ok) {
          throw new Error(
            (patientBody as { detail?: string }).detail ?? 'No patient set up yet.'
          );
        }
        const patientId = (patientBody as { id: string }).id;

        const res = await apiFetch(apiBaseUrl, '/api/dawa/schedule-demo-call', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            patientId,
            medicationId,
            delaySeconds,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail ?? `Scheduling failed (${res.status})`);

        setScheduledCall({
          doseEventId:  data.doseEventId,
          medicationId: data.medicationId,
          scheduledTime: data.scheduledTime,
          callStatus:   'scheduled',
          delayRemainingSeconds: data.delaySeconds,
        });

        startCountdown(data.delaySeconds);

        // Start polling to track state transitions
        if (!pollRef.current) {
          pollRef.current = setInterval(pollCallStatus, 3000);
        }
      } catch (err: unknown) {
        setScheduleError(err instanceof Error ? err.message : 'Failed to schedule call');
      } finally {
        setIsScheduling(false);
      }
    },
    [apiBaseUrl, pollCallStatus]
  );

  // ── P2: Reset demo ────────────────────────────────────────────────────────

  const resetDemo = useCallback(async () => {
    if (!apiBaseUrl) { setResetError('API URL not configured. Open settings.'); return; }
    setIsResetting(true);
    setResetError(null);
    try {
      const res = await apiFetch(apiBaseUrl, '/api/dawa/demo/reset', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `Reset failed (${res.status})`);

      // Clear all call state
      setScheduledCall(null);
      setCountdownSeconds(null);
      stopCountdown();
      stopPolling();
      setCallPhase('idle');
      setActiveCallId(null);
      setActiveDoseEventId(null);
      setCallError(null);

      // Reload fresh data
      await loadDemo();
    } catch (err: unknown) {
      setResetError(err instanceof Error ? err.message : 'Reset failed');
    } finally {
      setIsResetting(false);
    }
  }, [apiBaseUrl, loadDemo]);

  // ── Value ─────────────────────────────────────────────────────────────────

  const value: DawaContextValue = {
    apiBaseUrl, setApiBaseUrl,
    patient, medications, isLoading, loadError, refresh: loadDemo,
    vmrCues, addVmrCue, clearVmrCues, vmrResult, vmrLoading, runVmr,
    callPhase, activeCallId, activeDoseEventId, recentDoseEvents,
    dispatchCall, callError,
    // P2
    scheduledCall, countdownSeconds, isScheduling, scheduleDemo, scheduleError,
    isResetting, resetDemo, resetError,
  };

  return <DawaContext.Provider value={value}>{children}</DawaContext.Provider>;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useDawa(): DawaContextValue {
  const ctx = useContext(DawaContext);
  if (!ctx) throw new Error('useDawa must be used inside DawaProvider');
  return ctx;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function derivePhase(event: DoseEvent): CallPhase {
  const live = event.liveStatus;
  if (live?.failed || event.callStatus === 'failed') return 'failed';
  if (live?.completed || event.callStatus === 'completed') return 'completed';
  if (live?.answered || event.callStatus === 'answered') return 'answered';
  if (live?.ringing || event.callStatus === 'ringing') return 'ringing';
  if (live?.dialing || event.callStatus === 'dialing') return 'dialing';
  if (live?.dispatched || event.callStatus === 'dispatched') return 'dispatched';
  return 'idle';
}
