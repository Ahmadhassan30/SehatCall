import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { useAudioPlayer } from 'expo-audio';
import { Ionicons } from '@expo/vector-icons';
import { DawaHeader } from '@/components/DawaHeader';
import { useDawa } from '@/context/DawaContext';
import { useLanguage } from '@/context/LanguageContext';
import { useP3, type P3Voice } from '@/context/P3Context';
import { authenticatedMediaSource } from '@/lib/api';
import { authClient } from '@/lib/auth-client';
import { radius, ui } from '@/lib/ui';

function SectionTitle({ label }: { label: string }) {
  const { isUrdu } = useLanguage();
  return <Text style={[styles.sectionTitle, isUrdu && styles.rtlText]}>{label}</Text>;
}

function Field({
  label,
  value,
  onChangeText,
  placeholder,
  keyboardType,
}: {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  keyboardType?: 'default' | 'url';
}) {
  const { isUrdu } = useLanguage();
  return (
    <View style={styles.field}>
      <Text style={[styles.fieldLabel, isUrdu && styles.rtlText]}>{label}</Text>
      <TextInput
        style={[styles.input, isUrdu && styles.rtlInput]}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={ui.muted}
        keyboardType={keyboardType}
        autoCapitalize={keyboardType === 'url' ? 'none' : 'sentences'}
        autoCorrect={keyboardType !== 'url'}
      />
    </View>
  );
}

function VoiceRow({
  voice,
  selected,
  disabled,
  previewing,
  onSelect,
  onPreview,
}: {
  voice: P3Voice;
  selected: boolean;
  disabled: boolean;
  previewing: boolean;
  onSelect: () => void;
  onPreview: () => void;
}) {
  const { isUrdu, t } = useLanguage();
  return (
    <TouchableOpacity
      style={[styles.voiceRow, selected && styles.voiceSelected, disabled && styles.disabled]}
      onPress={onSelect}
      disabled={disabled}
      activeOpacity={0.75}
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled }}
    >
      <View style={[styles.voiceContent, isUrdu && styles.rowRtl]}>
        <View style={styles.voiceInfo}>
          <Text style={[styles.voiceName, selected && styles.voiceNameSelected, isUrdu && styles.rtlText]}>{voice.name}</Text>
          <Text style={[styles.voiceDescription, isUrdu && styles.rtlText]} numberOfLines={2}>
            {voice.description || voice.language}
          </Text>
        </View>
        <View style={[styles.voiceActions, isUrdu && styles.rowRtl]}>
          {selected ? <Ionicons name="checkmark-circle" size={21} color={ui.primary} /> : null}
          {voice.previewable ? (
            <TouchableOpacity
              style={styles.previewButton}
              onPress={(event) => {
                event.stopPropagation();
                onPreview();
              }}
              disabled={previewing || disabled}
              accessibilityLabel={t('common.preview')}
            >
              {previewing
                ? <ActivityIndicator size="small" color={ui.primary} />
                : <Ionicons name="volume-medium-outline" size={19} color={ui.primary} />}
            </TouchableOpacity>
          ) : null}
        </View>
      </View>
    </TouchableOpacity>
  );
}

export default function SettingsScreen() {
  const {
    patient,
    patientLoading,
    updatePatient,
    refreshPatient,
    voices,
    selectedVoiceId,
    voicesLoading,
    voicesError,
    refreshVoices,
    setVoice,
    voiceChanging,
    voiceChangeError,
  } = useP3();
  const { apiBaseUrl, setApiBaseUrl } = useDawa();
  const { language, setLanguage, isUrdu, t } = useLanguage();
  const router = useRouter();
  const { data: session } = authClient.useSession();
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [urlDraft, setUrlDraft] = useState(apiBaseUrl);
  const populatedPatientId = useRef<string | null>(null);
  const audioPlayer = useAudioPlayer(null);
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
  const rtl = isUrdu ? styles.rtlText : undefined;

  useEffect(() => {
    if (patient && populatedPatientId.current !== patient.id) {
      setName(patient.name);
      setAddress(patient.preferredAddress);
      populatedPatientId.current = patient.id;
    }
  }, [patient]);

  const handleSignOut = useCallback(async () => {
    try {
      await authClient.signOut();
    } finally {
      router.replace('/(auth)/sign-in');
    }
  }, [router]);

  const handleSavePatient = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      await updatePatient({ name: name.trim(), preferredAddress: address.trim() });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : t('common.updateFailed'));
    } finally {
      setSaving(false);
    }
  }, [address, name, t, updatePatient]);

  const handleSaveUrl = useCallback(async () => {
    await setApiBaseUrl(urlDraft.trim());
    await Promise.all([refreshPatient(), refreshVoices()]);
  }, [urlDraft, setApiBaseUrl, refreshPatient, refreshVoices]);

  const handleSetVoice = useCallback(async (voiceId: string) => {
    try {
      await setVoice(voiceId);
    } catch (error) {
      Alert.alert(t('settings.voiceFailed'), error instanceof Error ? error.message : t('common.tryAgain'));
    }
  }, [setVoice, t]);

  const handlePreview = useCallback(async (voice: P3Voice) => {
    if (!apiBaseUrl) {
      Alert.alert(t('settings.notConnected'), t('settings.configureBackend'));
      return;
    }
    if (playingVoiceId === voice.id) return;
    setPlayingVoiceId(voice.id);
    try {
      const source = await authenticatedMediaSource(apiBaseUrl, `/api/dawa/voices/${voice.id}/preview`);
      audioPlayer.replace(source);
      audioPlayer.play();
      setTimeout(() => setPlayingVoiceId(null), 8000);
    } catch {
      setPlayingVoiceId(null);
      Alert.alert(t('settings.previewFailed'));
    }
  }, [apiBaseUrl, audioPlayer, playingVoiceId, t]);

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <DawaHeader title={t('settings.title')} />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <SectionTitle label={t('settings.language')} />
        <View style={[styles.segmented, isUrdu && styles.rowRtl]}>
          {(['en', 'ur'] as const).map((option) => {
            const selected = language === option;
            return (
              <TouchableOpacity
                key={option}
                style={[styles.segment, selected && styles.segmentSelected]}
                onPress={() => setLanguage(option)}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
              >
                <Text style={[styles.segmentText, selected && styles.segmentTextSelected, option === 'ur' && styles.rtlText]}>
                  {option === 'en' ? t('language.english') : t('language.urdu')}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        <SectionTitle label={t('settings.account')} />
        <View style={styles.card}>
          {session?.user ? (
            <View style={[styles.accountRow, isUrdu && styles.rowRtl]}>
              <View style={styles.accountInfo}>
                <Text style={[styles.accountName, rtl]} numberOfLines={1}>{session.user.name || t('settings.caregiver')}</Text>
                <Text style={[styles.accountEmail, rtl]} numberOfLines={1}>{session.user.email}</Text>
              </View>
              <TouchableOpacity style={styles.signOutButton} onPress={handleSignOut}>
                <Text style={[styles.signOutText, rtl]}>{t('settings.signOut')}</Text>
              </TouchableOpacity>
            </View>
          ) : <ActivityIndicator color={ui.primary} />}
        </View>

        <SectionTitle label={t('settings.patient')} />
        <View style={styles.card}>
          {patientLoading && !patient ? <ActivityIndicator color={ui.primary} /> : (
            <>
              <Field label={t('settings.name')} value={name} onChangeText={setName} />
              <Field label={t('settings.address')} value={address} onChangeText={setAddress} />
              {saveError ? <View style={styles.errorPanel}><Text style={[styles.errorText, rtl]}>{saveError}</Text></View> : null}
              {saved ? <View style={styles.successPanel}><Text style={[styles.successText, rtl]}>{t('common.saved')}</Text></View> : null}
              <TouchableOpacity
                style={[styles.primaryButton, saving && styles.disabled]}
                onPress={handleSavePatient}
                disabled={saving}
              >
                {saving ? <ActivityIndicator color={ui.surface} size="small" /> : <Ionicons name="save-outline" size={18} color={ui.surface} />}
                <Text style={[styles.primaryButtonText, rtl]}>{t('settings.savePatient')}</Text>
              </TouchableOpacity>
            </>
          )}
        </View>

        <SectionTitle label={t('settings.voice')} />
        <View style={styles.card}>
          <Text style={[styles.helperText, rtl]}>{t('settings.voiceBody', { name: patient?.name ?? t('settings.patient') })}</Text>
          {patient?.preferredVoiceName ? (
            <Text style={[styles.currentVoice, rtl]}>
              {t('common.current')}  {patient.preferredVoiceName}
            </Text>
          ) : null}
          {voiceChangeError ? <View style={styles.errorPanel}><Text style={[styles.errorText, rtl]}>{voiceChangeError}</Text></View> : null}
          {voicesLoading ? <ActivityIndicator color={ui.primary} style={styles.loader} /> : voicesError ? (
            <View style={styles.errorPanel}><Text style={[styles.errorText, rtl]}>{voicesError}</Text></View>
          ) : voices.map((voice) => (
            <VoiceRow
              key={voice.id}
              voice={voice}
              selected={selectedVoiceId === voice.id}
              disabled={voiceChanging}
              previewing={playingVoiceId === voice.id}
              onSelect={() => selectedVoiceId !== voice.id && handleSetVoice(voice.id)}
              onPreview={() => handlePreview(voice)}
            />
          ))}
          {voiceChanging ? (
            <View style={[styles.progressRow, isUrdu && styles.rowRtl]}>
              <ActivityIndicator size="small" color={ui.primary} />
              <Text style={[styles.progressText, rtl]}>{t('settings.updatingVoice')}</Text>
            </View>
          ) : null}
        </View>

        <SectionTitle label={t('settings.connection')} />
        <View style={styles.card}>
          <Field
            label={t('settings.backendUrl')}
            value={urlDraft}
            onChangeText={setUrlDraft}
            placeholder="https://api.example.com"
            keyboardType="url"
          />
          <TouchableOpacity style={styles.secondaryButton} onPress={handleSaveUrl}>
            <Ionicons name="refresh-outline" size={18} color={ui.primary} />
            <Text style={[styles.secondaryButtonText, rtl]}>{t('settings.reconnect')}</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity style={[styles.devLink, isUrdu && styles.rowRtl]} onPress={() => router.push('/dev')}>
          <Text style={[styles.devLinkText, rtl]}>{t('settings.developer')}</Text>
          <Ionicons name={isUrdu ? 'chevron-back' : 'chevron-forward'} size={18} color={ui.muted} />
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: ui.canvas },
  scroll: { padding: 16, paddingBottom: 60 },
  sectionTitle: { fontFamily: 'Inter_700Bold', fontSize: 16, color: ui.text, marginTop: 28, marginBottom: 10 },
  card: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, padding: 18 },
  segmented: { flexDirection: 'row', backgroundColor: ui.surfaceMuted, borderRadius: radius.medium, padding: 3, borderWidth: 1, borderColor: ui.line },
  segment: { flex: 1, minHeight: 42, alignItems: 'center', justifyContent: 'center', borderRadius: radius.small },
  segmentSelected: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line },
  segmentText: { fontFamily: 'Inter_600SemiBold', fontSize: 15, color: ui.muted },
  segmentTextSelected: { fontFamily: 'Inter_700Bold', color: ui.text },
  accountRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  rowRtl: { flexDirection: 'row-reverse' },
  accountInfo: { flex: 1 },
  accountName: { fontFamily: 'Inter_700Bold', fontSize: 19, color: ui.text },
  accountEmail: { fontFamily: 'Inter_400Regular', fontSize: 14, color: ui.muted, marginTop: 4 },
  signOutButton: { borderWidth: 1, borderColor: ui.line, borderRadius: radius.small, paddingHorizontal: 12, paddingVertical: 8 },
  signOutText: { fontFamily: 'Inter_500Medium', fontSize: 13, color: ui.danger },
  field: { marginBottom: 14 },
  fieldLabel: { fontFamily: 'Inter_600SemiBold', fontSize: 14, color: ui.text, marginBottom: 7 },
  input: { minHeight: 50, fontFamily: 'Inter_500Medium', fontSize: 16, color: ui.text, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, paddingHorizontal: 12, backgroundColor: ui.canvas },
  rtlInput: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
  primaryButton: { minHeight: 52, borderRadius: radius.medium, backgroundColor: ui.primary, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 4 },
  primaryButtonText: { fontFamily: 'Inter_700Bold', fontSize: 16, color: ui.surface },
  secondaryButton: { minHeight: 46, borderRadius: radius.medium, borderWidth: 1, borderColor: ui.primary, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  secondaryButtonText: { fontFamily: 'Inter_700Bold', fontSize: 15, color: ui.primary },
  disabled: { opacity: 0.6 },
  helperText: { fontFamily: 'Inter_400Regular', fontSize: 15, lineHeight: 22, color: ui.muted, marginBottom: 14 },
  currentVoice: { fontFamily: 'Inter_700Bold', fontSize: 14, color: ui.primary, marginBottom: 12 },
  voiceRow: { borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, backgroundColor: ui.canvas, padding: 12, marginTop: 8 },
  voiceSelected: { borderColor: ui.primary, backgroundColor: ui.primarySoft },
  voiceContent: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  voiceInfo: { flex: 1 },
  voiceName: { fontFamily: 'Inter_700Bold', fontSize: 17, color: ui.text },
  voiceNameSelected: { fontFamily: 'Inter_700Bold', color: ui.primary },
  voiceDescription: { fontFamily: 'Inter_400Regular', fontSize: 13, lineHeight: 19, color: ui.muted, marginTop: 4 },
  voiceActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  previewButton: { width: 38, height: 38, borderRadius: radius.small, borderWidth: 1, borderColor: ui.primary, alignItems: 'center', justifyContent: 'center' },
  loader: { marginVertical: 18 },
  progressRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 12 },
  progressText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.muted },
  errorPanel: { backgroundColor: ui.dangerSoft, borderRadius: radius.small, padding: 10, marginBottom: 10 },
  errorText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.danger },
  successPanel: { backgroundColor: ui.successSoft, borderRadius: radius.small, padding: 10, marginBottom: 10 },
  successText: { fontFamily: 'Inter_500Medium', fontSize: 13, color: ui.success },
  devLink: { minHeight: 50, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: ui.line, marginTop: 28, paddingHorizontal: 2 },
  devLinkText: { fontFamily: 'Inter_400Regular', fontSize: 14, color: ui.muted },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});
