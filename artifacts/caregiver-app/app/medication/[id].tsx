/**
 * Edit medication form.
 */
import React, { useState, useCallback, useEffect } from 'react';
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
import { useRouter, useLocalSearchParams } from 'expo-router';
import { useP3, type P3Medication } from '@/context/P3Context';

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

function Field({ label, value, onChangeText, placeholder, multiline, hint }: {
  label: string; value: string; onChangeText: (t: string) => void;
  placeholder?: string; multiline?: boolean; hint?: string;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
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

function isValidTime(t: string): boolean {
  const m = t.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return false;
  const h = parseInt(m[1], 10), min = parseInt(m[2], 10);
  return h >= 0 && h <= 23 && min >= 0 && min <= 59;
}

export default function EditMedicationScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { medications, updateMedication, callMedicationNow } = useP3();
  const router = useRouter();

  const med: P3Medication | undefined = medications.find((m) => m.id === id);

  const [clinicalName, setClinicalName] = useState('');
  const [nickname, setNickname] = useState('');
  const [dosage, setDosage] = useState('');
  const [doseInstruction, setDoseInstruction] = useState('');
  const [foodInstruction, setFoodInstruction] = useState('');
  const [scheduleTime, setScheduleTime] = useState('');
  const [routineAnchor, setRoutineAnchor] = useState('');
  const [active, setActive] = useState(true);
  const [autoCallEnabled, setAutoCallEnabled] = useState(true);
  const [doctorInstructions, setDoctorInstructions] = useState('');
  const [doctorName, setDoctorName] = useState('');
  const [cues, setCues] = useState<Record<string, string>>({});

  const [saving, setSaving] = useState(false);
  const [calling, setCalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  // Populate from existing medication record
  useEffect(() => {
    if (!med) return;
    setClinicalName(med.clinicalName);
    setNickname(med.nickname ?? '');
    setDosage(med.dosage);
    setDoseInstruction(med.doseInstruction);
    setFoodInstruction(med.foodInstruction ?? '');
    setScheduleTime(med.scheduleTime);
    setRoutineAnchor(med.routineAnchor ?? '');
    setActive(med.active);
    setAutoCallEnabled(med.autoCallEnabled);
    setDoctorInstructions(med.doctorInstructions ?? '');
    setDoctorName(med.doctorName ?? '');
    setCues({ ...med.cues });
  }, [med?.id]);

  const updateCue = useCallback((key: string, value: string) => {
    setCues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleSave = useCallback(async () => {
    if (!med) return;
    setError(null);
    setWarnings([]);
    if (!clinicalName.trim()) { setError('Clinical name is required.'); return; }
    if (!dosage.trim()) { setError('Dosage is required.'); return; }
    if (!doseInstruction.trim()) { setError('Dose instruction is required.'); return; }
    if (!scheduleTime.trim() || !isValidTime(scheduleTime.trim())) {
      setError('Schedule time must be HH:MM (24-hour), e.g. 21:00');
      return;
    }
    const [h, m] = scheduleTime.split(':').map(Number);
    const normTime = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;

    setSaving(true);
    try {
      const updated = await updateMedication(med.id, {
        clinicalName: clinicalName.trim(),
        nickname: nickname.trim() || undefined,
        dosage: dosage.trim(),
        doseInstruction: doseInstruction.trim(),
        foodInstruction: foodInstruction.trim() || undefined,
        scheduleTime: normTime,
        routineAnchor: routineAnchor.trim() || undefined,
        active,
        autoCallEnabled,
        doctorInstructions: doctorInstructions.trim() || undefined,
        doctorName: doctorName.trim() || undefined,
        cues: Object.fromEntries(Object.entries(cues).filter(([, v]) => v.trim() !== undefined)),
      });
      if (updated.warnings?.length) {
        setWarnings(updated.warnings);
        setSaving(false);
        return;
      }
      router.back();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save medication');
      setSaving(false);
    }
  }, [med, clinicalName, nickname, dosage, doseInstruction, foodInstruction, scheduleTime, routineAnchor, active, autoCallEnabled, doctorInstructions, doctorName, cues, updateMedication, router]);

  const handleCallNow = useCallback(async () => {
    if (!med) return;
    setCalling(true);
    setError(null);
    try {
      await callMedicationNow(med.id);
      Alert.alert('Call dispatched', 'DAWA is calling Razia Bibi now.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Call failed');
    } finally {
      setCalling(false);
    }
  }, [med, callMedicationNow]);

  if (!med) {
    return (
      <View style={styles.screen}>
        <SafeAreaView edges={['top']} style={styles.topBar}>
          <TouchableOpacity onPress={() => router.back()} style={styles.cancelBtn}>
            <Text style={styles.cancelText}>Back</Text>
          </TouchableOpacity>
          <Text style={styles.screenTitle}>Edit Medication</Text>
          <View style={{ minWidth: 60 }} />
        </SafeAreaView>
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
          <ActivityIndicator color={C.blue} />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top']} style={styles.topBar}>
        <TouchableOpacity onPress={() => router.back()} style={styles.cancelBtn}>
          <Text style={styles.cancelText}>Cancel</Text>
        </TouchableOpacity>
        <Text style={styles.screenTitle}>Edit Medication</Text>
        <TouchableOpacity onPress={handleSave} disabled={saving} style={styles.doneBtn}>
          {saving ? <ActivityIndicator size="small" color={C.white} /> : <Text style={styles.doneText}>Save</Text>}
        </TouchableOpacity>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">

        {/* Existing warnings from last save */}
        {med.warnings?.length > 0 && !warnings.length && (
          <View style={styles.warnCard}>
            <Text style={styles.warnTitle}>Caution</Text>
            {med.warnings.map((w, i) => (
              <Text key={i} style={styles.warnText}>{w}</Text>
            ))}
          </View>
        )}

        {/* Call now — available regardless of auto_call_enabled */}
        <TouchableOpacity
          style={[styles.callBtn, calling && styles.callBtnDisabled]}
          onPress={handleCallNow}
          disabled={calling}
          activeOpacity={0.85}
        >
          {calling
            ? <><ActivityIndicator size="small" color={C.white} /><Text style={styles.callBtnText}> Calling…</Text></>
            : <Text style={styles.callBtnText}>Call Razia Bibi now</Text>
          }
        </TouchableOpacity>

        <Text style={styles.sectionTitle}>MEDICATION</Text>
        <View style={styles.card}>
          <Field label="Clinical name" value={clinicalName} onChangeText={setClinicalName} placeholder="Metformin" />
          <Field label="Nickname" value={nickname} onChangeText={setNickname} placeholder="raat wali goli" hint="What Razia Bibi calls it" />
          <Field label="Dosage" value={dosage} onChangeText={setDosage} placeholder="500 mg" />
          <Field label="Dose instruction" value={doseInstruction} onChangeText={setDoseInstruction} placeholder="1 tablet" />
          <Field label="Food instruction" value={foodInstruction} onChangeText={setFoodInstruction} placeholder="after dinner" />
        </View>

        <Text style={styles.sectionTitle}>SCHEDULE</Text>
        <View style={styles.card}>
          <Field label="Call time" value={scheduleTime} onChangeText={setScheduleTime} placeholder="21:00" hint="24-hour HH:MM" />
          <Field label="Routine anchor" value={routineAnchor} onChangeText={setRoutineAnchor} placeholder="after dinner" />
          <View style={styles.toggleRow}>
            <Text style={styles.label}>Active</Text>
            <Switch value={active} onValueChange={setActive} trackColor={{ true: C.blue, false: C.border }} thumbColor={C.white} />
          </View>
          <View style={styles.toggleRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Auto-call</Text>
              <Text style={styles.hint}>DAWA calls automatically at this time</Text>
            </View>
            <Switch value={autoCallEnabled} onValueChange={setAutoCallEnabled} disabled={!active} trackColor={{ true: C.blue, false: C.border }} thumbColor={C.white} />
          </View>
        </View>

        <Text style={styles.sectionTitle}>HOW RAZIA BIBI IDENTIFIES THIS MEDICINE</Text>
        <View style={styles.card}>
          {VALID_CUE_KEYS.map(({ key, label }) => (
            <Field key={key} label={label} value={cues[key] ?? ''} onChangeText={(v) => updateCue(key, v)} placeholder="e.g. white" />
          ))}
        </View>

        <Text style={styles.sectionTitle}>DOCTOR'S INSTRUCTIONS</Text>
        <View style={styles.card}>
          <Text style={styles.cueIntro}>
            DAWA will never override the structured fields above based on this note. If there is a conflict, it will ask the caregiver to verify.
          </Text>
          <Field label="Doctor's name" value={doctorName} onChangeText={setDoctorName} placeholder="Dr. Ahmed" />
          <Field label="Instructions" value={doctorInstructions} onChangeText={setDoctorInstructions} multiline placeholder="e.g. Take with a full glass of water" />
        </View>

        {error ? (
          <View style={styles.errBanner}><Text style={styles.errText}>{error}</Text></View>
        ) : null}

        {warnings.length > 0 ? (
          <View style={styles.warnCard}>
            <Text style={styles.warnTitle}>Saved — please review</Text>
            {warnings.map((w, i) => <Text key={i} style={styles.warnText}>{w}</Text>)}
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
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 16, paddingBottom: 12,
    backgroundColor: C.cream, borderBottomWidth: 1, borderBottomColor: C.border,
  },
  cancelBtn: { padding: 4, minWidth: 60 },
  cancelText: { fontFamily: 'Inter_400Regular', fontSize: 16, color: C.muted },
  screenTitle: { fontFamily: 'Inter_700Bold', fontSize: 17, color: C.navy },
  doneBtn: { backgroundColor: C.blue, borderRadius: 10, paddingHorizontal: 16, paddingVertical: 8, minWidth: 60, alignItems: 'center' },
  doneText: { fontFamily: 'Inter_600SemiBold', fontSize: 15, color: C.white },

  scroll: { padding: 20, paddingBottom: 60 },
  sectionTitle: { fontFamily: 'Inter_600SemiBold', fontSize: 11, color: C.muted, letterSpacing: 1.1, marginTop: 20, marginBottom: 10 },
  card: { backgroundColor: C.white, borderRadius: 16, padding: 18, shadowColor: C.navy, shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.05, shadowRadius: 5, elevation: 2 },
  field: { marginBottom: 14 },
  label: { fontFamily: 'Inter_500Medium', fontSize: 14, color: C.navy, marginBottom: 4 },
  hint: { fontFamily: 'Inter_400Regular', fontSize: 12, color: C.muted, marginBottom: 5 },
  cueIntro: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted, lineHeight: 19, marginBottom: 14 },
  input: { fontFamily: 'Inter_400Regular', fontSize: 16, color: C.navy, borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, backgroundColor: C.cream },
  inputMulti: { minHeight: 80, textAlignVertical: 'top', paddingTop: 12 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 8 },

  callBtn: { backgroundColor: C.blue, borderRadius: 14, paddingVertical: 16, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 8, marginBottom: 20 },
  callBtnDisabled: { opacity: 0.6 },
  callBtnText: { fontFamily: 'Inter_600SemiBold', fontSize: 17, color: C.white },

  errBanner: { backgroundColor: C.errBg, borderRadius: 10, padding: 14, marginTop: 16, borderLeftWidth: 3, borderLeftColor: C.err },
  errText: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.err },
  warnCard: { backgroundColor: C.warnBg, borderRadius: 12, padding: 16, marginTop: 16, borderLeftWidth: 3, borderLeftColor: C.warn },
  warnTitle: { fontFamily: 'Inter_600SemiBold', fontSize: 15, color: C.warn, marginBottom: 8 },
  warnText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.warn, lineHeight: 18, marginBottom: 6 },
  doneWarnBtn: { backgroundColor: C.warn, borderRadius: 10, paddingVertical: 12, alignItems: 'center', marginTop: 8 },
  doneWarnText: { fontFamily: 'Inter_600SemiBold', fontSize: 15, color: C.white },
});
