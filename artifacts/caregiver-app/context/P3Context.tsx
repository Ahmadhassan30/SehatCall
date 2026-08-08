/**
 * P3Context — Caregiver setup + voice selection.
 *
 * Wraps all P3 API endpoints. Kept separate from DawaContext (P1/P2) so
 * developer tools in DawaContext remain untouched.
 */
import { apiFetch } from '@/lib/api';
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useDawa } from './DawaContext';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface P3Patient {
  id: string;
  name: string;
  preferredAddress: string;
  language: string;
  literacyMode: string;
  /** Partially hidden, e.g. "+92*******567". The full number stays server-side. */
  maskedPhone: string | null;
  /** Until this is true, DAWA will not place any reminder call. */
  phoneVerified: boolean;
  /** True only while the server has an active phone-code challenge. */
  phoneVerificationInProgress: boolean;
  preferredVoiceId: string | null;
  preferredVoiceName: string | null;
}

export interface P3NewPatient {
  name: string;
  preferredAddress: string;
  phone: string;
  language?: string;
}

export interface P3PhoneChallenge {
  status: string;
  maskedPhone: string;
  expiresInSeconds: number;
  resendAvailableInSeconds: number;
}

export interface P3Medication {
  id: string;
  patientId: string;
  clinicalName: string;
  nickname: string | null;
  dosage: string;
  doseInstruction: string;
  foodInstruction: string | null;
  scheduleTime: string; // HH:MM 24h
  routineAnchor: string | null;
  active: boolean;
  autoCallEnabled: boolean;
  doctorInstructions: string | null;
  doctorName: string | null;
  verifiedAt: string | null;
  updatedAt: string | null;
  cues: Record<string, string>;
  warnings: string[];
}

export interface P3NextCall {
  medicationId: string;
  nickname: string;
  clinicalName: string;
  dosage: string;
  scheduleTime: string;
  scheduledFor: string;
  secondsUntil: number;
  autoCallEnabled: boolean;
}

export interface P3Call {
  id: string;
  medicationId: string;
  nickname: string;
  clinicalName: string | null;
  scheduledTime: string;
  callStatus: string;
  adherenceOutcome: string | null;
  adherenceLabel: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface P3Voice {
  id: string;
  name: string;
  description: string | null;
  language: string;
  previewable: boolean;
}

export interface MedicationPayload {
  clinicalName: string;
  dosage: string;
  doseInstruction: string;
  scheduleTime: string;
  nickname?: string;
  foodInstruction?: string;
  routineAnchor?: string;
  active?: boolean;
  autoCallEnabled?: boolean;
  doctorInstructions?: string;
  doctorName?: string;
  cues?: Record<string, string>;
}

interface P3ContextValue {
  // Patient
  patient: P3Patient | null;
  patientLoading: boolean;
  patientError: string | null;
  refreshPatient: () => Promise<void>;
  updatePatient: (
    fields: Partial<Pick<P3Patient, 'name' | 'preferredAddress' | 'language' | 'literacyMode'>>
      & { phone?: string }
  ) => Promise<void>;
  createPatient: (fields: P3NewPatient) => Promise<P3Patient>;
  sendPhoneCode: () => Promise<P3PhoneChallenge>;
  verifyPhoneCode: (code: string) => Promise<void>;

  // Medications
  medications: P3Medication[];
  medicationsLoading: boolean;
  medicationsError: string | null;
  refreshMedications: () => Promise<void>;
  createMedication: (payload: MedicationPayload) => Promise<P3Medication>;
  updateMedication: (id: string, patch: Partial<MedicationPayload> & { active?: boolean; autoCallEnabled?: boolean }) => Promise<P3Medication>;
  callMedicationNow: (id: string) => Promise<{ callId: string }>;

  // Next call
  nextCall: P3NextCall | null;
  nextCallLoading: boolean;
  refreshNextCall: () => Promise<void>;
  secondsUntilNext: number | null;

  // Call history
  calls: P3Call[];
  callsLoading: boolean;
  callsError: string | null;
  refreshCalls: () => Promise<void>;

  // Active call phase (from callMedicationNow)
  activeCallPhase: 'idle' | 'calling' | 'failed';
  activeCallError: string | null;
  clearCallState: () => void;

  // Voices
  voices: P3Voice[];
  selectedVoiceId: string | null;
  voicesLoading: boolean;
  voicesError: string | null;
  refreshVoices: () => Promise<void>;
  setVoice: (voiceId: string) => Promise<void>;
  voiceChanging: boolean;
  voiceChangeError: string | null;
}

const P3Context = createContext<P3ContextValue | null>(null);

export function P3Provider({ children }: { children: React.ReactNode }) {
  const { apiBaseUrl } = useDawa();

  // Patient
  const [patient, setPatient] = useState<P3Patient | null>(null);
  const [patientLoading, setPatientLoading] = useState(false);
  const [patientError, setPatientError] = useState<string | null>(null);

  // Medications
  const [medications, setMedications] = useState<P3Medication[]>([]);
  const [medicationsLoading, setMedicationsLoading] = useState(false);
  const [medicationsError, setMedicationsError] = useState<string | null>(null);

  // Next call
  const [nextCall, setNextCall] = useState<P3NextCall | null>(null);
  const [nextCallLoading, setNextCallLoading] = useState(false);
  const [secondsUntilNext, setSecondsUntilNext] = useState<number | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Calls
  const [calls, setCalls] = useState<P3Call[]>([]);
  const [callsLoading, setCallsLoading] = useState(false);
  const [callsError, setCallsError] = useState<string | null>(null);

  // Active call
  const [activeCallPhase, setActiveCallPhase] = useState<'idle' | 'calling' | 'failed'>('idle');
  const [activeCallError, setActiveCallError] = useState<string | null>(null);

  // Voices
  const [voices, setVoices] = useState<P3Voice[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string | null>(null);
  const [voicesLoading, setVoicesLoading] = useState(false);
  const [voicesError, setVoicesError] = useState<string | null>(null);
  const [voiceChanging, setVoiceChanging] = useState(false);
  const [voiceChangeError, setVoiceChangeError] = useState<string | null>(null);

  // ── Fetch helpers ─────────────────────────────────────────────────────────

  const api = useCallback(
    async (path: string, options?: RequestInit) => {
      // apiFetch attaches the Better Auth session cookie from SecureStore.
      // It throws immediately if apiBaseUrl is empty.
      const res = await apiFetch(apiBaseUrl, path, options);
      const text = await res.text();
      let body: any = {};
      try {
        body = text ? JSON.parse(text) : {};
      } catch {
        body = {};
      }
      if (!res.ok) {
        const message =
          body.detail ??
          body.message ??
          body.error ??
          (text.trim() ? text.trim().slice(0, 240) : undefined) ??
          `Server error ${res.status}`;
        throw new Error(String(message));
      }
      return body;
    },
    [apiBaseUrl]
  );

  // ── Patient ───────────────────────────────────────────────────────────────

  const refreshPatient = useCallback(async () => {
    setPatientLoading(true);
    setPatientError(null);
    try {
      const data = await api('/api/dawa/patient');
      setPatient(data as P3Patient);
    } catch (e) {
      setPatientError(e instanceof Error ? e.message : 'Failed to load patient');
    } finally {
      setPatientLoading(false);
    }
  }, [api]);

  const updatePatient = useCallback(
    async (
      fields: Partial<Pick<P3Patient, 'name' | 'preferredAddress' | 'language' | 'literacyMode'>>
        & { phone?: string }
    ) => {
      const data = await api('/api/dawa/patient', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      });
      setPatient(data as P3Patient);
    },
    [api]
  );

  /** Create this caregiver's patient. The number starts unverified. */
  const createPatient = useCallback(
    async (fields: P3NewPatient) => {
      const data = (await api('/api/dawa/patient', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      })) as P3Patient;
      setPatient(data);
      setPatientError(null);
      return data;
    },
    [api]
  );

  /** Ring the patient's number and speak a verification code down the line. */
  const sendPhoneCode = useCallback(
    async () =>
      (await api('/api/dawa/patient/phone/send-code', {
        method: 'POST',
      })) as P3PhoneChallenge,
    [api]
  );

  const verifyPhoneCode = useCallback(
    async (code: string) => {
      await api('/api/dawa/patient/phone/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      // Verification flips a server-side flag; re-read rather than guess.
      await refreshPatient();
    },
    [api, refreshPatient]
  );

  // ── Medications ───────────────────────────────────────────────────────────

  const refreshMedications = useCallback(async () => {
    setMedicationsLoading(true);
    setMedicationsError(null);
    try {
      const data = await api('/api/dawa/medications');
      setMedications((data as { medications: P3Medication[] }).medications ?? []);
    } catch (e) {
      setMedicationsError(e instanceof Error ? e.message : 'Failed to load medications');
    } finally {
      setMedicationsLoading(false);
    }
  }, [api]);

  const createMedication = useCallback(
    async (payload: MedicationPayload): Promise<P3Medication> => {
      const data = await api('/api/dawa/medications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      await refreshMedications();
      return data as P3Medication;
    },
    [api, refreshMedications]
  );

  const updateMedication = useCallback(
    async (id: string, patch: Partial<MedicationPayload> & { active?: boolean; autoCallEnabled?: boolean }): Promise<P3Medication> => {
      const data = await api(`/api/dawa/medications/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      await refreshMedications();
      return data as P3Medication;
    },
    [api, refreshMedications]
  );

  const callMedicationNow = useCallback(
    async (id: string): Promise<{ callId: string }> => {
      setActiveCallPhase('calling');
      setActiveCallError(null);
      try {
        const data = await api(`/api/dawa/medications/${id}/call`, { method: 'POST' });
        setActiveCallPhase('idle');
        await refreshCalls();
        return data as { callId: string };
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Call failed';
        setActiveCallPhase('failed');
        setActiveCallError(msg);
        throw e;
      }
    },
    [api]
  );

  const clearCallState = useCallback(() => {
    setActiveCallPhase('idle');
    setActiveCallError(null);
  }, []);

  // ── Next call ─────────────────────────────────────────────────────────────

  const refreshNextCall = useCallback(async () => {
    setNextCallLoading(true);
    try {
      const data = await api('/api/dawa/next-call');
      const nc = (data as { nextCall: P3NextCall | null }).nextCall;
      setNextCall(nc);
      setSecondsUntilNext(nc?.secondsUntil ?? null);
    } catch {
      // Silent — next-call is supplementary
    } finally {
      setNextCallLoading(false);
    }
  }, [api]);

  // Countdown tick
  useEffect(() => {
    if (tickRef.current) clearInterval(tickRef.current);
    if (secondsUntilNext === null || secondsUntilNext <= 0) return;
    tickRef.current = setInterval(() => {
      setSecondsUntilNext((prev) => {
        if (prev === null || prev <= 1) {
          if (tickRef.current) clearInterval(tickRef.current);
          refreshNextCall();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
  }, [nextCall?.scheduledFor]);

  // ── Calls ─────────────────────────────────────────────────────────────────

  const refreshCalls = useCallback(async () => {
    setCallsLoading(true);
    setCallsError(null);
    try {
      const data = await api('/api/dawa/calls?limit=30');
      setCalls((data as { calls: P3Call[] }).calls ?? []);
    } catch (e) {
      setCallsError(e instanceof Error ? e.message : 'Failed to load calls');
    } finally {
      setCallsLoading(false);
    }
  }, [api]);

  // ── Voices ────────────────────────────────────────────────────────────────

  const refreshVoices = useCallback(async () => {
    setVoicesLoading(true);
    setVoicesError(null);
    try {
      const data = await api('/api/dawa/voices');
      setVoices((data as { voices: P3Voice[] }).voices ?? []);
      setSelectedVoiceId((data as { selectedVoiceId: string | null }).selectedVoiceId ?? null);
    } catch (e) {
      setVoicesError(e instanceof Error ? e.message : 'Failed to load voices');
    } finally {
      setVoicesLoading(false);
    }
  }, [api]);

  const setVoice = useCallback(
    async (voiceId: string) => {
      setVoiceChanging(true);
      setVoiceChangeError(null);
      try {
        const data = await api('/api/dawa/patient/voice', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ voiceId }),
        });
        setPatient(data as P3Patient);
        setSelectedVoiceId((data as P3Patient).preferredVoiceId);
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Could not change voice';
        setVoiceChangeError(msg);
        throw e;
      } finally {
        setVoiceChanging(false);
      }
    },
    [api]
  );

  // ── Boot load ─────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!apiBaseUrl) return;
    refreshPatient();
    refreshMedications();
    refreshNextCall();
    refreshCalls();
    refreshVoices();
  }, [apiBaseUrl]);

  const value: P3ContextValue = {
    patient, patientLoading, patientError, refreshPatient, updatePatient,
    createPatient, sendPhoneCode, verifyPhoneCode,
    medications, medicationsLoading, medicationsError, refreshMedications, createMedication, updateMedication, callMedicationNow,
    nextCall, nextCallLoading, refreshNextCall, secondsUntilNext,
    calls, callsLoading, callsError, refreshCalls,
    activeCallPhase, activeCallError, clearCallState,
    voices, selectedVoiceId, voicesLoading, voicesError, refreshVoices, setVoice, voiceChanging, voiceChangeError,
  };

  return <P3Context.Provider value={value}>{children}</P3Context.Provider>;
}

export function useP3(): P3ContextValue {
  const ctx = useContext(P3Context);
  if (!ctx) throw new Error('useP3 must be used inside P3Provider');
  return ctx;
}
