/**
 * Add medication form.
 */
import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Switch,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { useP3, type MedicationPayload } from '@/context/P3Context';

const C = {
  cream: '#F7F3E8',
  blue: '#6F9FB5',
  navy: '#243642',
  white: '#FFFFFF',
  border: '#D8D0BC',
  muted: '#7A8A8E',
  err: '#B83232',
  errBg: '#FDEAEA',
  warn: '#C97B2A',
  warnBg: '#FDF3E3',
};

const VALID_CUE_KEYS: Array<{ key: string; label: string }> = [
  { key: 'package_color', label: 'Package colour' },
  { key: 'stripe_color', label: 'Stripe colour' },
  { key: 'tablet_shape', label: 'Tablet shape' },
  { key: 'storage_location', label: 'Where it is kept' },
];

function Field({ label, value, onChangeText, placeholder, multiline, hint, required }: {
  label: string; value: string; onChangeText: (t: string) => void;
  placeholder?: string; multiline?: boolean; hint?: string; required?: boolean;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>
        {label}{required ? <Text style={{ color: C.err }}> *</Text> : null}
      </Text>
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
      <TextInput
        style={[styles.input, multiline && styles.inputMulti]}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={C.muted}
        multiline={multiline}
        numberOfLines={multiline ? 3 : 1}
      />
    </View>
  );
}

function SectionTitle({ text }: { text: string }) {
  return <Text style={styles.sectionTitle}>{text}</Text>;
}

/** Strict HH:MM validation — the backend rejects anything else. */
function isValidTime(t: string): boolean {
  const m = t.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return false;
  const h = parseInt(m[1], 10), min = parseInt(m[2], 10);
  return h >= 0 && h <= 23 && min >= 0 && min <= 59;
}

export default function NewMedicationScreen() {
  const { createMedication } = useP3();
  const router = useRouter();

  const [clinicalName, setClinicalName] = useState('');
  const [nickname, setNickname] = useState('');
  const [dosage, setDosage] = useState('');
  const [doseInstruction, setDoseInstruction] = useState('');
  const [foodInstruction, setFoodInstruction] = useState('');
  const [scheduleTime, setScheduleTime] = useState('');
  const [routineAnchor, setRoutineAnchor] = useState('');
  const [autoCallEnabled, setAutoCallEnabled] = useState(true);
  const [doctorInstructions, setDoctorInstructions] = useState('');
  const [doctorName, setDoctorName] = useState('');
  const [cues, setCues] = useState<Record<string, string>>({});

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  const updateCue = useCallback((key: string, value: string) => {
    setCues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleSave = useCallback(async () => {
    setError(null);
    if (!clinicalName.trim()) { setError('Clinical name is required.'); return; }
    if (!dosage.trim()) { setError('Dosage is required.'); return; }
    if (!doseInstruction.trim()) { setError('Dose instruction is required.'); return; }
    if (!scheduleTime.trim() || !isValidTime(scheduleTime.trim())) {
      setError('Schedule time must be HH:MM (24-hour), e.g. 21:00');
      return;
    }

    // Normalise HH:MM
    const [h, m] = scheduleTime.split(':').map(Number);
    const normTime = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;

    setSaving(true);
    try {
      const payload: MedicationPayload = {
        clinicalName: clinicalName.trim(),
        dosage: dosage.trim(),
        doseInstruction: doseInstruction.trim(),
        scheduleTime: normTime,
        nickname: nickname.trim() || undefined,
        foodInstruction: foodInstruction.trim() || undefined,
        routineAnchor: routineAnchor.trim() || undefined,
        autoCallEnabled,
        active: true,
        doctorInstructions: doctorInstructions.trim() || undefined,
        doctorName: doctorName.trim() || undefined,
        cues: Object.fromEntries(Object.entries(cues).filter(([, v]) => v.trim())),
      };
      const med = await createMedication(payload);
      if (med.warnings?.length) {
        // Show but never auto-resolve — save succeeded, surface caution
        setWarnings(med.warnings);
        setSaving(false);
        return; // hold on screen so caregiver reads the warning, then let them go back
      }
      router.back();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save medication');
      setSaving(false);
    }
  }, [clinicalName, nickname, dosage, doseInstruction, foodInstruction, scheduleTime, routineAnchor, autoCallEnabled, doctorInstructions, doctorName, cues, createMedication, router]);

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top']} style={styles.topBar}>
        <TouchableOpacity onPress={() => router.back()} style={styles.cancelBtn}>
          <Text style={styles.cancelText}>Cancel</Text>
        </TouchableOpacity>
        <Text style={styles.screenTitle}>Add Medication</Text>
        <TouchableOpacity onPress={handleSave} disabled={saving} style={styles.doneBtn}>
          {saving ? <ActivityIndicator size="small" color={C.white} /> : <Text style={styles.doneText}>Save</Text>}
        </TouchableOpacity>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        {/* ── Clinical info ────────────────────────────────────────── */}
        <SectionTitle text="MEDICATION" />
        <View style={styles.card}>
          <Field label="Clinical name" value={clinicalName} onChangeText={setClinicalName} placeholder="e.g. Metformin" required />
          <Field label="Nickname" value={nickname} onChangeText={setNickname} placeholder="e.g. raat wali goli" hint="What Razia Bibi calls it" />
          <Field label="Dosage" value={dosage} onChangeText={setDosage} placeholder="e.g. 500 mg" required />
          <Field label="Dose instruction" value={doseInstruction} onChangeText={setDoseInstruction} placeholder="e.g. 1 tablet" required />
          <Field label="Food instruction" value={foodInstruction} onChangeText={setFoodInstruction} placeholder="e.g. after dinner" />
        </View>

        {/* ── Schedule ─────────────────────────────────────────────── */}
        <SectionTitle text="SCHEDULE" />
        <View style={styles.card}>
          <Field
            label="Call time"
            value={scheduleTime}
            onChangeText={setScheduleTime}
            placeholder="21:00"
            hint="24-hour format HH:MM"
            required
          />
          <Field label="Routine anchor" value={routineAnchor} onChangeText={setRoutineAnchor} placeholder="e.g. after dinner" hint="Helps Razia Bibi remember when" />

          <View style={styles.toggleRow}>
            <View>
              <Text style={styles.label}>Auto-call</Text>
              <Text style={styles.hint}>DAWA will call automatically at this time</Text>
            </View>
            <Switch
              value={autoCallEnabled}
              onValueChange={setAutoCallEnabled}
              trackColor={{ true: C.blue, false: C.border }}
              thumbColor={C.white}
            />
          </View>
        </View>

        {/* ── Visual cues ───────────────────────────────────────────── */}
        <SectionTitle text="HOW RAZIA BIBI IDENTIFIES THIS MEDICINE" />
        <View style={styles.card}>
          <Text style={styles.cueIntro}>
            These details help DAWA ask Razia Bibi to find the right medicine by sight — the only way someone who cannot read can verify they have the right tablet.
          </Text>
          {VALID_CUE_KEYS.map(({ key, label }) => (
            <Field
              key={key}
              label={label}
              value={cues[key] ?? ''}
              onChangeText={(v) => updateCue(key, v)}
              placeholder="e.g. white"
            />
          ))}
        </View>

        {/* ── Doctor note ───────────────────────────────────────────── */}
        <SectionTitle text="DOCTOR'S INSTRUCTIONS (OPTIONAL)" />
        <View style={styles.card}>
          <Text style={styles.cueIntro}>
            DAWA never overrides the structured fields above. If this note conflicts with them, DAWA will ask the caregiver to verify rather than choosing on its own.
          </Text>
          <Field label="Doctor's name" value={doctorName} onChangeText={setDoctorName} placeholder="Dr. Ahmed" />
          <Field label="Instructions" value={doctorInstructions} onChangeText={setDoctorInstructions} placeholder="e.g. Take with a full glass of water" multiline />
        </View>

        {/* ── Errors / Warnings ────────────────────────────────────── */}
        {error ? (
          <View style={styles.errBanner}><Text style={styles.errText}>{error}</Text></View>
        ) : null}

        {warnings.length > 0 ? (
          <View style={styles.warnCard}>
            <Text style={styles.warnTitle}>Saved — please review</Text>
            {warnings.map((w, i) => (
              <Text key={i} style={styles.warnText}>{w}</Text>
            ))}
            <TouchableOpacity style={styles.doneWarnBtn} onPress={() => router.back()}>
              <Text style={styles.doneWarnText}>Got it, go back</Text>
            </TouchableOpacity>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.cream },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingBottom: 12,
    backgroundColor: C.cream,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  cancelBtn: { padding: 4, minWidth: 60 },
  cancelText: { fontFamily: 'Inter_400Regular', fontSize: 16, color: C.muted },
  screenTitle: { fontFamily: 'Inter_700Bold', fontSize: 17, color: C.navy },
  doneBtn: { backgroundColor: C.blue, borderRadius: 10, paddingHorizontal: 16, paddingVertical: 8, minWidth: 60, alignItems: 'center' },
  doneText: { fontFamily: 'Inter_600SemiBold', fontSize: 15, color: C.white },

  scroll: { padding: 20, paddingBottom: 60 },
  sectionTitle: {
    fontFamily: 'Inter_600SemiBold', fontSize: 11, color: C.muted,
    letterSpacing: 1.1, marginTop: 20, marginBottom: 10,
  },
  card: {
    backgroundColor: C.white, borderRadius: 16, padding: 18,
    shadowColor: C.navy, shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05, shadowRadius: 5, elevation: 2,
  },
  field: { marginBottom: 14 },
  label: { fontFamily: 'Inter_500Medium', fontSize: 14, color: C.navy, marginBottom: 4 },
  hint: { fontFamily: 'Inter_400Regular', fontSize: 12, color: C.muted, marginBottom: 5 },
  input: {
    fontFamily: 'Inter_400Regular', fontSize: 16, color: C.navy,
    borderWidth: 1, borderColor: C.border, borderRadius: 10,
    paddingHorizontal: 14, paddingVertical: 12, backgroundColor: C.cream,
  },
  inputMulti: { minHeight: 80, textAlignVertical: 'top', paddingTop: 12 },
  toggleRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingTop: 8,
  },

  cueIntro: {
    fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted,
    lineHeight: 19, marginBottom: 14,
  },

  errBanner: {
    backgroundColor: C.errBg, borderRadius: 10, padding: 14, marginTop: 16,
    borderLeftWidth: 3, borderLeftColor: C.err,
  },
  errText: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.err },

  warnCard: {
    backgroundColor: C.warnBg, borderRadius: 12, padding: 16, marginTop: 16,
    borderLeftWidth: 3, borderLeftColor: C.warn,
  },
  warnTitle: { fontFamily: 'Inter_600SemiBold', fontSize: 15, color: C.warn, marginBottom: 8 },
  warnText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.warn, lineHeight: 18, marginBottom: 6 },
  doneWarnBtn: { backgroundColor: C.warn, borderRadius: 10, paddingVertical: 12, alignItems: 'center', marginTop: 8 },
  doneWarnText: { fontFamily: 'Inter_600SemiBold', fontSize: 15, color: C.white },
});
