/**
 * Settings tab — patient preferences, DAWA voice selection, developer tools link.
 */
import React, { useState, useCallback, useRef } from 'react';
import {
  View,
  Text,
  ScrollView,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  Pressable,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { useAudioPlayer } from 'expo-audio';
import { useP3, type P3Voice } from '@/context/P3Context';
import { useDawa } from '@/context/DawaContext';
import { DawaHeader } from '@/components/DawaHeader';
import { authClient } from '@/lib/auth-client';

const C = {
  cream: '#F7F3E8',
  blue: '#6F9FB5',
  navy: '#243642',
  white: '#FFFFFF',
  border: '#D8D0BC',
  muted: '#7A8A8E',
  warn: '#C97B2A',
  warnBg: '#FDF3E3',
  err: '#B83232',
  errBg: '#FDEAEA',
  ok: '#2D7A4F',
};

function SectionTitle({ label }: { label: string }) {
  return <Text style={styles.sectionTitle}>{label}</Text>;
}

function Field({ label, value, onChangeText, placeholder, multiline }: {
  label: string; value: string; onChangeText: (t: string) => void;
  placeholder?: string; multiline?: boolean;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
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

function VoiceRow({ voice, selected, onSelect, onPreview, previewing }: {
  voice: P3Voice;
  selected: boolean;
  onSelect: () => void;
  onPreview: () => void;
  previewing: boolean;
}) {
  return (
    <TouchableOpacity
      style={[styles.voiceRow, selected && styles.voiceRowSelected]}
      onPress={onSelect}
      activeOpacity={0.8}
    >
      <View style={styles.voiceInfo}>
        <Text style={[styles.voiceName, selected && styles.voiceNameSelected]}>
          {voice.name}
        </Text>
        {voice.description ? (
          <Text style={styles.voiceDesc}>{voice.description}</Text>
        ) : (
          <Text style={styles.voiceLang}>{voice.language}</Text>
        )}
      </View>
      <View style={styles.voiceActions}>
        {selected && <View style={styles.selectedDot} />}
        {voice.previewable && (
          <TouchableOpacity
            style={styles.previewBtn}
            onPress={onPreview}
            disabled={previewing}
          >
            {previewing ? (
              <ActivityIndicator size="small" color={C.blue} />
            ) : (
              <Text style={styles.previewBtnText}>Preview</Text>
            )}
          </TouchableOpacity>
        )}
      </View>
    </TouchableOpacity>
  );
}

export default function SettingsScreen() {
  const {
    patient, patientLoading, updatePatient, refreshPatient,
    voices, selectedVoiceId, voicesLoading, voicesError, refreshVoices, setVoice,
    voiceChanging, voiceChangeError,
  } = useP3();
  const { apiBaseUrl, setApiBaseUrl } = useDawa();
  const router = useRouter();
  const { data: session } = authClient.useSession();

  const handleSignOut = useCallback(async () => {
    try {
      await authClient.signOut();
    } finally {
      router.replace('/(auth)/sign-in');
    }
  }, [router]);

  // Patient form state
  const [name, setName] = useState('');
  const [addr, setAddr] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Populate form from loaded patient
  const populatedRef = useRef(false);
  React.useEffect(() => {
    if (patient && !populatedRef.current) {
      setName(patient.name);
      setAddr(patient.preferredAddress);
      populatedRef.current = true;
    }
  }, [patient]);

  // URL editor
  const [urlDraft, setUrlDraft] = useState(apiBaseUrl);

  // Audio playback (expo-audio)
  const audioPlayer = useAudioPlayer(null);
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);

  const handleSavePatient = useCallback(async () => {
    setSaving(true);
    setSaveErr(null);
    setSaved(false);
    try {
      await updatePatient({ name: name.trim(), preferredAddress: addr.trim() });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : 'Could not save');
    } finally {
      setSaving(false);
    }
  }, [name, addr, updatePatient]);

  const handleSaveUrl = useCallback(async () => {
    await setApiBaseUrl(urlDraft);
    await Promise.all([refreshPatient(), refreshVoices()]);
  }, [urlDraft, setApiBaseUrl, refreshPatient, refreshVoices]);

  const handleSetVoice = useCallback(
    async (voiceId: string) => {
      try {
        await setVoice(voiceId);
      } catch (e) {
        Alert.alert(
          'Voice not changed',
          e instanceof Error ? e.message : 'An error occurred',
        );
      }
    },
    [setVoice]
  );

  const handlePreview = useCallback(
    async (voice: P3Voice) => {
      if (!apiBaseUrl) {
        Alert.alert('Not connected', 'Configure the backend URL first.');
        return;
      }
      if (playingVoiceId === voice.id) return; // already playing, let it finish
      setPlayingVoiceId(voice.id);
      try {
        await audioPlayer.replace({ uri: `${apiBaseUrl}/api/dawa/voices/${voice.id}/preview` });
        audioPlayer.play();
        // Reset playing indicator after a reasonable max preview duration
        setTimeout(() => setPlayingVoiceId(null), 8000);
      } catch {
        setPlayingVoiceId(null);
        Alert.alert('Preview failed', 'Could not play voice preview. Check your connection.');
      }
    },
    [apiBaseUrl, playingVoiceId, audioPlayer]
  );

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <DawaHeader title="Settings" />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">

        {/* ── Account ──────────────────────────────────────────────── */}
        <SectionTitle label="ACCOUNT" />
        <View style={styles.card}>
          {session?.user ? (
            <View style={styles.accountRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.accountName} numberOfLines={1}>
                  {session.user.name || 'Caregiver'}
                </Text>
                <Text style={styles.accountEmail} numberOfLines={1}>
                  {session.user.email}
                </Text>
              </View>
              <TouchableOpacity
                style={styles.signOutBtn}
                onPress={handleSignOut}
                activeOpacity={0.7}
              >
                <Text style={styles.signOutBtnText}>Sign out</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <ActivityIndicator color={C.blue} />
          )}
        </View>

        {/* ── Patient profile ──────────────────────────────────────── */}
        <SectionTitle label="PATIENT" />
        <View style={styles.card}>
          {patientLoading && !patient ? (
            <ActivityIndicator color={C.blue} />
          ) : (
            <>
              <Field label="Name" value={name} onChangeText={setName} placeholder="Razia Bibi" />
              <Field label="How DAWA addresses her" value={addr} onChangeText={setAddr} placeholder="Ammi" />

              {saveErr ? (
                <View style={styles.errBanner}><Text style={styles.errText}>{saveErr}</Text></View>
              ) : null}
              {saved ? (
                <View style={styles.okBanner}><Text style={styles.okText}>Saved</Text></View>
              ) : null}

              <TouchableOpacity
                style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
                onPress={handleSavePatient}
                disabled={saving}
              >
                {saving
                  ? <ActivityIndicator color="#FFF" size="small" />
                  : <Text style={styles.saveBtnText}>Save patient details</Text>
                }
              </TouchableOpacity>
            </>
          )}
        </View>

        {/* ── Voice ───────────────────────────────────────────────── */}
        <SectionTitle label="DAWA VOICE" />
        <View style={styles.card}>
          <Text style={styles.voiceNote}>
            Choose the voice Razia Bibi hears on every reminder call. Tap Preview to hear a short sample before selecting.
          </Text>
          {patient?.preferredVoiceName ? (
            <View style={styles.currentVoiceRow}>
              <Text style={styles.currentVoiceLabel}>Current: </Text>
              <Text style={styles.currentVoiceName}>{patient.preferredVoiceName}</Text>
            </View>
          ) : null}

          {voiceChangeError ? (
            <View style={styles.errBanner}>
              <Text style={styles.errText}>{voiceChangeError}</Text>
            </View>
          ) : null}

          {voicesLoading ? (
            <ActivityIndicator color={C.blue} style={{ marginVertical: 16 }} />
          ) : voicesError ? (
            <View style={styles.errBanner}><Text style={styles.errText}>{voicesError}</Text></View>
          ) : (
            voices.map((v) => (
              <VoiceRow
                key={v.id}
                voice={v}
                selected={selectedVoiceId === v.id}
                onSelect={() => !voiceChanging && handleSetVoice(v.id)}
                onPreview={() => handlePreview(v)}
                previewing={playingVoiceId === v.id}
              />
            ))
          )}
          {voiceChanging && (
            <View style={styles.changingBanner}>
              <ActivityIndicator size="small" color={C.blue} />
              <Text style={styles.changingText}>Updating voice…</Text>
            </View>
          )}
        </View>

        {/* ── Backend URL ─────────────────────────────────────────── */}
        <SectionTitle label="CONNECTION" />
        <View style={styles.card}>
          <Text style={styles.fieldLabel}>Backend URL</Text>
          <TextInput
            style={styles.input}
            value={urlDraft}
            onChangeText={setUrlDraft}
            placeholder="https://your-repl.replit.dev"
            placeholderTextColor={C.muted}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />
          <TouchableOpacity style={styles.saveBtn} onPress={handleSaveUrl}>
            <Text style={styles.saveBtnText}>Save & reconnect</Text>
          </TouchableOpacity>
        </View>

        {/* ── Developer tools link ─────────────────────────────────── */}
        <TouchableOpacity
          style={styles.devLink}
          onPress={() => router.push('/dev')}
          activeOpacity={0.7}
        >
          <Text style={styles.devLinkText}>Developer tools</Text>
          <Text style={styles.devLinkArrow}>›</Text>
        </TouchableOpacity>

      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.cream },
  scroll: { padding: 20, paddingBottom: 60 },

  sectionTitle: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 11,
    color: C.muted,
    letterSpacing: 1.1,
    marginBottom: 10,
    marginTop: 24,
  },

  card: {
    backgroundColor: C.white,
    borderRadius: 16,
    padding: 18,
    shadowColor: C.navy,
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 6,
    elevation: 2,
  },

  field: { marginBottom: 14 },
  fieldLabel: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.muted, marginBottom: 6 },
  input: {
    fontFamily: 'Inter_400Regular',
    fontSize: 16,
    color: C.navy,
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    backgroundColor: C.cream,
  },
  inputMulti: { minHeight: 80, textAlignVertical: 'top', paddingTop: 12 },

  saveBtn: {
    backgroundColor: C.blue,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 6,
  },
  saveBtnDisabled: { opacity: 0.6 },
  saveBtnText: { fontFamily: 'Inter_600SemiBold', fontSize: 16, color: '#FFF' },

  errBanner: {
    backgroundColor: '#FDEAEA',
    borderRadius: 8,
    padding: 10,
    marginBottom: 10,
    borderLeftWidth: 3,
    borderLeftColor: C.err,
  },
  errText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.err },
  okBanner: {
    backgroundColor: '#EAF5EE',
    borderRadius: 8,
    padding: 10,
    marginBottom: 10,
  },
  okText: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.ok },

  voiceNote: {
    fontFamily: 'Inter_400Regular',
    fontSize: 14,
    color: C.muted,
    lineHeight: 20,
    marginBottom: 12,
  },
  currentVoiceRow: { flexDirection: 'row', marginBottom: 14 },
  currentVoiceLabel: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.muted },
  currentVoiceName: { fontFamily: 'Inter_600SemiBold', fontSize: 14, color: C.navy },

  voiceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: C.border,
    marginBottom: 8,
    backgroundColor: C.cream,
  },
  voiceRowSelected: {
    borderColor: C.blue,
    backgroundColor: '#EDF4F8',
  },
  voiceInfo: { flex: 1 },
  voiceName: { fontFamily: 'Inter_500Medium', fontSize: 15, color: C.navy },
  voiceNameSelected: { fontFamily: 'Inter_600SemiBold', color: C.blue },
  voiceDesc: { fontFamily: 'Inter_400Regular', fontSize: 12, color: C.muted, marginTop: 2 },
  voiceLang: { fontFamily: 'Inter_400Regular', fontSize: 12, color: C.muted, marginTop: 2 },
  voiceActions: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  selectedDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: C.blue },
  previewBtn: {
    borderWidth: 1,
    borderColor: C.blue,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
    minWidth: 64,
    alignItems: 'center',
  },
  previewBtnText: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.blue },

  changingBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
  },
  changingText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted },

  devLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 32,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: C.white + 'CC',
  },
  devLinkText: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.muted },
  devLinkArrow: { fontFamily: 'Inter_400Regular', fontSize: 18, color: C.muted },

  // Account section
  accountRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  accountName: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 16,
    color: C.navy,
    marginBottom: 2,
  },
  accountEmail: {
    fontFamily: 'Inter_400Regular',
    fontSize: 13,
    color: C.muted,
  },
  signOutBtn: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: C.border,
  },
  signOutBtnText: {
    fontFamily: 'Inter_500Medium',
    fontSize: 13,
    color: C.err,
  },
});
