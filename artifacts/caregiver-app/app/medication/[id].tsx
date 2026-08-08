import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/context/LanguageContext';
import { useP3 } from '@/context/P3Context';
import { radius, ui } from '@/lib/ui';

function isValidTime(value: string): boolean {
  const match = value.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return false;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59;
}

function Field({
  label,
  value,
  onChangeText,
  placeholder,
  hint,
  multiline,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  placeholder?: string;
  hint?: string;
  multiline?: boolean;
}) {
  const { isUrdu } = useLanguage();
  return (
    <View style={styles.field}>
      <Text style={[styles.label, isUrdu && styles.rtlText]}>{label}</Text>
      {hint ? <Text style={[styles.hint, isUrdu && styles.rtlText]}>{hint}</Text> : null}
      <TextInput
        style={[styles.input, multiline && styles.multiline, isUrdu && styles.rtlInput]}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={ui.muted}
        multiline={multiline}
        numberOfLines={multiline ? 3 : 1}
      />
    </View>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  const { isUrdu } = useLanguage();
  return <Text style={[styles.sectionTitle, isUrdu && styles.rtlText]}>{children}</Text>;
}

export default function EditMedicationScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { patient, medications, updateMedication, callMedicationNow } = useP3();
  const { isUrdu, t } = useLanguage();
  const router = useRouter();
  const medicine = medications.find((item) => item.id === id);
  const [clinicalName, setClinicalName] = useState('');
  const [nickname, setNickname] = useState('');
  const [dosage, setDosage] = useState('');
  const [doseInstruction, setDoseInstruction] = useState('');
  const [foodInstruction, setFoodInstruction] = useState('');
  const [scheduleTime, setScheduleTime] = useState('');
  const [routineAnchor, setRoutineAnchor] = useState('');
  const [active, setActive] = useState(true);
  const [automaticCalls, setAutomaticCalls] = useState(true);
  const [doctorInstructions, setDoctorInstructions] = useState('');
  const [doctorName, setDoctorName] = useState('');
  const [cues, setCues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [calling, setCalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const rtl = isUrdu ? styles.rtlText : undefined;
  const cueFields = [
    ['package_color', t('form.packageColour')],
    ['stripe_color', t('form.stripeColour')],
    ['tablet_shape', t('form.tabletShape')],
    ['storage_location', t('form.storage')],
  ] as const;

  useEffect(() => {
    if (!medicine) return;
    setClinicalName(medicine.clinicalName);
    setNickname(medicine.nickname ?? '');
    setDosage(medicine.dosage);
    setDoseInstruction(medicine.doseInstruction);
    setFoodInstruction(medicine.foodInstruction ?? '');
    setScheduleTime(medicine.scheduleTime);
    setRoutineAnchor(medicine.routineAnchor ?? '');
    setActive(medicine.active);
    setAutomaticCalls(medicine.autoCallEnabled);
    setDoctorInstructions(medicine.doctorInstructions ?? '');
    setDoctorName(medicine.doctorName ?? '');
    setCues({ ...medicine.cues });
  }, [medicine?.id]);

  const handleSave = useCallback(async () => {
    if (!medicine) return;
    setError(null);
    setWarnings([]);
    if (!clinicalName.trim()) return setError(t('form.requiredClinical'));
    if (!dosage.trim()) return setError(t('form.requiredDosage'));
    if (!doseInstruction.trim()) return setError(t('form.requiredDose'));
    if (!isValidTime(scheduleTime.trim())) return setError(t('form.invalidTime'));

    const [hour, minute] = scheduleTime.split(':').map(Number);
    const normalisedTime = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    setSaving(true);
    try {
      const updated = await updateMedication(medicine.id, {
        clinicalName: clinicalName.trim(),
        nickname: nickname.trim() || undefined,
        dosage: dosage.trim(),
        doseInstruction: doseInstruction.trim(),
        foodInstruction: foodInstruction.trim() || undefined,
        scheduleTime: normalisedTime,
        routineAnchor: routineAnchor.trim() || undefined,
        active,
        autoCallEnabled: automaticCalls,
        doctorInstructions: doctorInstructions.trim() || undefined,
        doctorName: doctorName.trim() || undefined,
        cues: Object.fromEntries(Object.entries(cues).filter(([, value]) => value.trim())),
      });
      if (updated.warnings?.length) {
        setWarnings(updated.warnings);
        return;
      }
      router.back();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t('form.saveFailed'));
    } finally {
      setSaving(false);
    }
  }, [active, automaticCalls, clinicalName, cues, doctorInstructions, doctorName, dosage, doseInstruction, foodInstruction, medicine, nickname, router, routineAnchor, scheduleTime, t, updateMedication]);

  const handleCallNow = useCallback(async () => {
    if (!medicine) return;
    setCalling(true);
    setError(null);
    try {
      await callMedicationNow(medicine.id);
      Alert.alert(t('form.callDispatched'), t('form.callDispatchedBody', { name: patient?.name ?? t('settings.patient') }));
    } catch (callError) {
      setError(callError instanceof Error ? callError.message : t('form.callFailed'));
    } finally {
      setCalling(false);
    }
  }, [callMedicationNow, medicine, patient?.name, t]);

  if (!medicine) {
    return (
      <View style={styles.screen}>
        <StatusBar style="dark" />
        <SafeAreaView edges={['top']} style={[styles.topBar, isUrdu && styles.rowRtl]}>
          <TouchableOpacity style={styles.iconButton} onPress={() => router.back()} accessibilityLabel={t('common.back')}>
            <Ionicons name={isUrdu ? 'arrow-forward' : 'arrow-back'} size={21} color={ui.text} />
          </TouchableOpacity>
          <Text style={[styles.screenTitle, rtl]}>{t('form.editTitle')}</Text>
          <View style={styles.iconButton} />
        </SafeAreaView>
        <View style={styles.loader}><ActivityIndicator color={ui.primary} /></View>
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top']} style={[styles.topBar, isUrdu && styles.rowRtl]}>
        <TouchableOpacity style={styles.iconButton} onPress={() => router.back()} accessibilityLabel={t('common.cancel')}>
          <Ionicons name={isUrdu ? 'arrow-forward' : 'arrow-back'} size={21} color={ui.text} />
        </TouchableOpacity>
        <Text style={[styles.screenTitle, rtl]}>{t('form.editTitle')}</Text>
        <TouchableOpacity style={[styles.iconButton, styles.saveButton]} onPress={handleSave} disabled={saving} accessibilityLabel={t('common.save')}>
          {saving ? <ActivityIndicator size="small" color={ui.surface} /> : <Ionicons name="checkmark" size={22} color={ui.surface} />}
        </TouchableOpacity>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        {medicine.warnings?.length && !warnings.length ? (
          <View style={styles.warningPanel}>
            <Text style={[styles.warningTitle, rtl]}>{t('form.caution')}</Text>
            {medicine.warnings.map((warning, index) => <Text key={index} style={[styles.warningText, rtl]}>{warning}</Text>)}
          </View>
        ) : null}

        <TouchableOpacity style={[styles.callButton, calling && styles.disabled]} onPress={handleCallNow} disabled={calling}>
          {calling ? <ActivityIndicator size="small" color={ui.surface} /> : <Ionicons name="call-outline" size={19} color={ui.surface} />}
          <Text style={[styles.callButtonText, rtl]}>{calling ? t('form.calling') : t('form.callPatient')}</Text>
        </TouchableOpacity>

        <SectionTitle>{t('form.medication')}</SectionTitle>
        <View style={styles.card}>
          <Field label={t('form.clinicalName')} value={clinicalName} onChangeText={setClinicalName} placeholder={t('form.exampleClinical')} />
          <Field label={t('form.nickname')} value={nickname} onChangeText={setNickname} placeholder={t('form.exampleNickname')} hint={t('form.nicknameHint')} />
          <Field label={t('form.dosage')} value={dosage} onChangeText={setDosage} placeholder={t('form.exampleDosage')} />
          <Field label={t('form.doseInstruction')} value={doseInstruction} onChangeText={setDoseInstruction} placeholder={t('form.exampleDose')} />
          <Field label={t('form.foodInstruction')} value={foodInstruction} onChangeText={setFoodInstruction} placeholder={t('form.exampleFood')} />
        </View>

        <SectionTitle>{t('form.schedule')}</SectionTitle>
        <View style={styles.card}>
          <Field label={t('form.callTime')} value={scheduleTime} onChangeText={setScheduleTime} placeholder="21:00" hint={t('form.timeHint')} />
          <Field label={t('form.routineAnchor')} value={routineAnchor} onChangeText={setRoutineAnchor} placeholder={t('form.exampleRoutine')} hint={t('form.routineHint')} />
          <View style={[styles.toggleRow, isUrdu && styles.rowRtl]}>
            <Text style={[styles.label, rtl]}>{t('common.active')}</Text>
            <Switch value={active} onValueChange={setActive} trackColor={{ true: ui.primary, false: ui.line }} thumbColor={ui.surface} />
          </View>
          <View style={[styles.toggleRow, styles.toggleDivider, isUrdu && styles.rowRtl]}>
            <View style={styles.toggleCopy}>
              <Text style={[styles.label, rtl]}>{t('form.automaticCalls')}</Text>
              <Text style={[styles.hint, rtl]}>{t('form.automaticCallsHint')}</Text>
            </View>
            <Switch value={automaticCalls} onValueChange={setAutomaticCalls} disabled={!active} trackColor={{ true: ui.primary, false: ui.line }} thumbColor={ui.surface} />
          </View>
        </View>

        <SectionTitle>{t('form.identification')}</SectionTitle>
        <View style={styles.card}>
          <Text style={[styles.intro, rtl]}>{t('form.identificationBody')}</Text>
          {cueFields.map(([key, label]) => (
            <Field key={key} label={label} value={cues[key] ?? ''} onChangeText={(value) => setCues((current) => ({ ...current, [key]: value }))} placeholder={t('form.exampleColour')} />
          ))}
        </View>

        <SectionTitle>{t('form.doctorInstructions')}</SectionTitle>
        <View style={styles.card}>
          <Text style={[styles.intro, rtl]}>{t('form.doctorBody')}</Text>
          <Field label={t('form.doctorName')} value={doctorName} onChangeText={setDoctorName} placeholder={t('form.exampleDoctor')} />
          <Field label={t('form.instructions')} value={doctorInstructions} onChangeText={setDoctorInstructions} placeholder={t('form.exampleInstructions')} multiline />
        </View>

        {error ? <View style={styles.errorPanel}><Text style={[styles.errorText, rtl]}>{error}</Text></View> : null}
        {warnings.length ? (
          <View style={styles.warningPanel}>
            <Text style={[styles.warningTitle, rtl]}>{t('form.savedReview')}</Text>
            {warnings.map((warning, index) => <Text key={index} style={[styles.warningText, rtl]}>{warning}</Text>)}
            <TouchableOpacity style={styles.warningButton} onPress={() => router.back()}>
              <Text style={[styles.warningButtonText, rtl]}>{t('form.return')}</Text>
            </TouchableOpacity>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: ui.canvas },
  topBar: { minHeight: 58, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingBottom: 8, backgroundColor: ui.surface, borderBottomWidth: 1, borderBottomColor: ui.line },
  rowRtl: { flexDirection: 'row-reverse' },
  iconButton: { width: 40, height: 40, borderRadius: radius.medium, alignItems: 'center', justifyContent: 'center' },
  saveButton: { backgroundColor: ui.primary },
  screenTitle: { flex: 1, fontFamily: 'Inter_700Bold', fontSize: 21, color: ui.text, textAlign: 'center', marginHorizontal: 10 },
  loader: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: 16, paddingBottom: 60 },
  callButton: { minHeight: 54, backgroundColor: ui.primary, borderRadius: radius.medium, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 18 },
  callButtonText: { fontFamily: 'Inter_700Bold', fontSize: 17, color: ui.surface },
  disabled: { opacity: 0.6 },
  sectionTitle: { fontFamily: 'Inter_700Bold', fontSize: 16, color: ui.text, marginTop: 28, marginBottom: 10 },
  card: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, padding: 18 },
  field: { marginBottom: 14 },
  label: { fontFamily: 'Inter_600SemiBold', fontSize: 15, color: ui.text, marginBottom: 6 },
  hint: { fontFamily: 'Inter_400Regular', fontSize: 13, lineHeight: 19, color: ui.muted, marginBottom: 7 },
  input: { minHeight: 50, fontFamily: 'Inter_500Medium', fontSize: 16, color: ui.text, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, paddingHorizontal: 12, backgroundColor: ui.canvas },
  multiline: { minHeight: 88, paddingTop: 12, textAlignVertical: 'top' },
  rtlInput: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
  toggleRow: { minHeight: 52, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 16 },
  toggleDivider: { borderTopWidth: 1, borderTopColor: ui.line, paddingTop: 8, marginTop: 4 },
  toggleCopy: { flex: 1 },
  intro: { fontFamily: 'Inter_400Regular', fontSize: 14, lineHeight: 21, color: ui.muted, marginBottom: 18 },
  errorPanel: { backgroundColor: ui.dangerSoft, borderLeftWidth: 3, borderLeftColor: ui.danger, borderRadius: radius.small, padding: 12, marginTop: 16 },
  errorText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.danger },
  warningPanel: { backgroundColor: ui.warningSoft, borderLeftWidth: 3, borderLeftColor: ui.warning, borderRadius: radius.medium, padding: 16, marginTop: 16 },
  warningTitle: { fontFamily: 'Inter_700Bold', fontSize: 17, color: ui.warning, marginBottom: 8 },
  warningText: { fontFamily: 'Inter_400Regular', fontSize: 13, lineHeight: 19, color: ui.warning, marginBottom: 6 },
  warningButton: { minHeight: 46, backgroundColor: ui.warning, borderRadius: radius.medium, alignItems: 'center', justifyContent: 'center', marginTop: 10 },
  warningButtonText: { fontFamily: 'Inter_700Bold', fontSize: 15, color: ui.surface },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});
