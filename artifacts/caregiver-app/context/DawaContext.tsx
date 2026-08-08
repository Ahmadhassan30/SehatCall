/**
 * DawaContext — P1 state management for the DAWA caregiver app.
 *
 * Replaces the P0-B CallContext.  All API calls use the new P1 endpoints:
 *   GET  /api/dawa/demo          — patient + medications on mount
 *   POST /api/dawa/vmr/resolve   — deterministic medication ID from visual cues
 *   POST /api/dawa/demo-call     — dispatch a verified Uplift call
 *   GET  /api/dawa/call-status   — dose events + live telephony status
 *
 * No admin token is required — P1 demo endpoints are open for the hackathon.
 * Phone number is always read from TEST_PHONE_NUMBER on the server.
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

  // Call state
  callPhase: CallPhase;
  activeCallId: string | null;
  activeDoseEventId: string | null;
  recentDoseEvents: DoseEvent[];
  dispatchCall: (patientId: string, medicationId: string) => Promise<void>;
  callError: string | null;
}

// ─── Context ─────────────────────────────────────────────────────────────────

const DawaContext = createContext<DawaContextValue | null>(null);

const STORAGE_KEY_URL = 'dawa_api_url';

function deriveDefaultUrl(): string {
  // In Replit dev, EXPO_PUBLIC_DOMAIN is set to $REPLIT_DEV_DOMAIN
  // The api-server proxy is accessible at that domain (path /api/*)
  const domain = process.env['EXPO_PUBLIC_DOMAIN'];
  if (domain) {
    return `https://${domain}`;
  }
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

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Persist URL ──────────────────────────────────────────────────────────

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY_URL).then((stored) => {
      if (stored && stored.trim()) {
        setApiBaseUrlState(stored.trim());
      }
    });
  }, []);

  const setApiBaseUrl = useCallback(async (url: string) => {
    const trimmed = url.trim();
    setApiBaseUrlState(trimmed);
    await AsyncStorage.setItem(STORAGE_KEY_URL, trimmed);
  }, []);

  // ── Load demo data ───────────────────────────────────────────────────────

  const loadDemo = useCallback(async () => {
    if (!apiBaseUrl) return;
    setIsLoading(true);
    setLoadError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/dawa/demo`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setPatient(data.patient ?? null);
      setMedications(data.medications ?? []);
      setRecentDoseEvents(data.doseEvents ?? []);
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : 'Failed to connect to DAWA backend');
    } finally {
      setIsLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    loadDemo();
  }, [loadDemo]);

  // ── VMR ──────────────────────────────────────────────────────────────────

  const addVmrCue = useCallback((key: string, value: string) => {
    setVmrCues((prev) => ({ ...prev, [key]: value }));
    setVmrResult(null); // reset on cue change
  }, []);

  const clearVmrCues = useCallback(() => {
    setVmrCues({});
    setVmrResult(null);
  }, []);

  const runVmr = useCallback(async () => {
    if (!apiBaseUrl || !patient || Object.keys(vmrCues).length === 0) return;
    setVmrLoading(true);
    try {
      const res = await fetch(`${apiBaseUrl}/api/dawa/vmr/resolve`, {
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

  // Re-run VMR automatically when cues change
  useEffect(() => {
    if (Object.keys(vmrCues).length > 0 && patient) {
      runVmr();
    }
  }, [vmrCues, patient, runVmr]);

  // ── Poll call status ──────────────────────────────────────────────────────

  const pollCallStatus = useCallback(async () => {
    if (!apiBaseUrl) return;
    try {
      const res = await fetch(`${apiBaseUrl}/api/dawa/call-status?limit=5`);
      if (!res.ok) return;
      const data = await res.json();
      const events: DoseEvent[] = data.doseEvents ?? [];
      setRecentDoseEvents(events);

      // Update callPhase from the active event
      if (activeDoseEventId) {
        const active = events.find((e) => e.id === activeDoseEventId);
        if (active) {
          const phase = derivePhase(active);
          setCallPhase(phase);
          if (active.callId) setActiveCallId(active.callId);
          if (phase === 'completed' || phase === 'failed') {
            stopPolling();
          }
        }
      }
    } catch {
      // Silently ignore poll failures
    }
  }, [apiBaseUrl, activeDoseEventId]);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => {
    return () => stopPolling();
  }, []);

  // ── Dispatch call ────────────────────────────────────────────────────────

  const dispatchCall = useCallback(
    async (patientId: string, medicationId: string) => {
      if (!apiBaseUrl) {
        setCallError('API URL not configured. Open settings.');
        return;
      }
      setCallPhase('dispatching');
      setCallError(null);
      setActiveCallId(null);
      setActiveDoseEventId(null);
      stopPolling();

      try {
        const res = await fetch(`${apiBaseUrl}/api/dawa/demo-call`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ patientId, medicationId }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail ?? `Call dispatch failed (${res.status})`);
        }
        setActiveCallId(data.callId ?? null);
        setActiveDoseEventId(data.doseEventId ?? null);
        setCallPhase('dispatched');
        // Start polling every 3 s
        pollRef.current = setInterval(pollCallStatus, 3000);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setCallPhase('failed');
        setCallError(msg);
      }
    },
    [apiBaseUrl, pollCallStatus]
  );

  const value: DawaContextValue = {
    apiBaseUrl,
    setApiBaseUrl,
    patient,
    medications,
    isLoading,
    loadError,
    refresh: loadDemo,
    vmrCues,
    addVmrCue,
    clearVmrCues,
    vmrResult,
    vmrLoading,
    runVmr,
    callPhase,
    activeCallId,
    activeDoseEventId,
    recentDoseEvents,
    dispatchCall,
    callError,
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
