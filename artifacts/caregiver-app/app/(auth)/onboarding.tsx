/**
 * DAWA Caregiver — Onboarding (Set up your patient)
 *
 * A new account starts completely empty. This screen is where the caregiver
 * creates their own patient and proves the phone number DAWA will dial.
 *
 * Two steps:
 *   1. "details" — who the patient is and which number to call
 *   2. "verify"  — DAWA rings that number and speaks a code, which the
 *                  caregiver types back here
 *
 * Verification is a phone CALL rather than an SMS on purpose: the only
 * capability DAWA needs from a number is that someone answers a call on it,
 * so the check proves exactly the thing that matters. No reminder call is ever
 * placed until this step succeeds.
 */
import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { useDawa } from '@/context/DawaContext';
import { useP3 } from '@/context/P3Context';
import { authClient } from '@/lib/auth-client';

const C = {
  cream: '#F7F3E8',
  blue: '#6F9FB5',
  navy: '#243642',
  white: '#FFFFFF',
  muted: '#7A8A8E',
  border: '#D8D0BC',
  err: '#B83232',
  errBg: '#FDEAEA',
  ok: '#2D7A4F',
  okBg: '#EAF5EE',
};

type Step = 'details' | 'verify';

export default function OnboardingScreen() {
  const router = useRouter();
  const { apiBaseUrl } = useDawa();
  const { data: session } = authClient.useSession();
  const { patient, createPatient, updatePatient, sendPhoneCode, verifyPhoneCode } = useP3();

  const [step, setStep] = useState<Step>('details');
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [maskedPhone, setMaskedPhone] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // A caregiver who closed the app mid-setup comes back to the step they were
  // actually on, rather than being asked to create a patient that exists.
  // A patient with no number yet still belongs on the details step — there is
  // nothing to verify until a number is entered.
  useEffect(() => {
    if (!patient) return;
    setName((v) => v || patient.name);
    setAddress((v) => v || patient.preferredAddress);
    if (!patient.phoneVerified && patient.maskedPhone) {
      setMaskedPhone(patient.maskedPhone);
      setStep('verify');
    }
  }, [patient]);

  // Resend cooldown ticker.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const requireApi = (): boolean => {
    if (!apiBaseUrl) {
      setError('Backend URL not configured. Open Settings, set the API URL, then come back.');
      return false;
    }
    return true;
  };

  const describe = (e: unknown) =>
    e instanceof Error ? e.message : 'Something went wrong. Please try again.';

  const handleCreate = async () => {
    if (!requireApi()) return;
    if (!name.trim() || !address.trim() || !phone.trim()) {
      setError('Please fill in all three fields.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // The patient may already exist — a retry after a failed dispatch, or a
      // caregiver coming back to correct the number. Update rather than create,
      // since an account may only ever have one patient.
      if (patient) {
        await updatePatient({
          name: name.trim(),
          preferredAddress: address.trim(),
          phone: phone.trim(),
        });
      } else {
        await createPatient({
          name: name.trim(),
          preferredAddress: address.trim(),
          phone: phone.trim(),
        });
      }
      const challenge = await sendPhoneCode();
      setMaskedPhone(challenge.maskedPhone);
      setCooldown(challenge.resendAvailableInSeconds ?? 60);
      setStep('verify');
      setNotice(null);
    } catch (e) {
      setError(describe(e));
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    if (!requireApi() || cooldown > 0) return;
    setLoading(true);
    setError(null);
    try {
      const challenge = await sendPhoneCode();
      setMaskedPhone(challenge.maskedPhone);
      setCooldown(challenge.resendAvailableInSeconds ?? 60);
      setNotice('Calling again now.');
    } catch (e) {
      setError(describe(e));
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    if (!requireApi()) return;
    if (!code.trim()) {
      setError('Enter the code you heard on the call.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await verifyPhoneCode(code.trim());
      router.replace('/(tabs)');
    } catch (e) {
      setError(describe(e));
      setCode('');
    } finally {
      setLoading(false);
    }
  };

  const handleSignOut = async () => {
    await authClient.signOut();
    router.replace('/(auth)/sign-in');
  };

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <StatusBar style="dark" />

        <View style={styles.header}>
          <Text style={styles.wordmark}>DAWA</Text>
          {session?.user?.name ? (
            <Text style={styles.greeting}>Hello, {session.user.name.split(' ')[0]}</Text>
          ) : null}
        </View>

        <View style={styles.card}>
          {step === 'details' ? (
            <>
              <Text style={styles.cardTitle}>Who are we calling?</Text>
              <Text style={styles.cardBody}>
                Tell us about the person DAWA will remind. You can change any of
                this later.
              </Text>

              <Text style={styles.label}>Their name</Text>
              <TextInput
                style={styles.input}
                value={name}
                onChangeText={setName}
                placeholder="e.g. Razia Bibi"
                placeholderTextColor={C.muted}
                autoCapitalize="words"
                editable={!loading}
              />

              <Text style={styles.label}>What DAWA should call them</Text>
              <TextInput
                style={styles.input}
                value={address}
                onChangeText={setAddress}
                placeholder="e.g. Ammi"
                placeholderTextColor={C.muted}
                autoCapitalize="words"
                editable={!loading}
              />
              <Text style={styles.hint}>
                DAWA greets them by this name on every call.
              </Text>

              <Text style={styles.label}>Their phone number</Text>
              <TextInput
                style={styles.input}
                value={phone}
                onChangeText={setPhone}
                placeholder="+923001234567"
                placeholderTextColor={C.muted}
                keyboardType="phone-pad"
                autoCorrect={false}
                editable={!loading}
              />
              <Text style={styles.hint}>
                Include the country code, starting with “+”. We&apos;ll ring this
                number once now to make sure it reaches them.
              </Text>
            </>
          ) : (
            <>
              <Text style={styles.cardTitle}>Check the phone</Text>
              <Text style={styles.cardBody}>
                DAWA is calling{' '}
                <Text style={styles.strong}>{maskedPhone ?? 'that number'}</Text>{' '}
                and will read out a 6-digit code. Enter it below.
              </Text>

              <Text style={styles.label}>Verification code</Text>
              <TextInput
                style={[styles.input, styles.codeInput]}
                value={code}
                onChangeText={setCode}
                placeholder="123456"
                placeholderTextColor={C.muted}
                keyboardType="number-pad"
                maxLength={6}
                editable={!loading}
              />

              <TouchableOpacity
                onPress={handleResend}
                disabled={loading || cooldown > 0}
                style={styles.resendLink}
              >
                <Text style={[styles.resendText, cooldown > 0 && styles.resendMuted]}>
                  {cooldown > 0 ? `Call again in ${cooldown}s` : 'Didn’t get the call? Try again'}
                </Text>
              </TouchableOpacity>
            </>
          )}

          {notice ? (
            <View style={styles.okBanner}>
              <Text style={styles.okText}>{notice}</Text>
            </View>
          ) : null}

          {error ? (
            <View style={styles.errBanner}>
              <Text style={styles.errText}>{error}</Text>
            </View>
          ) : null}

          <TouchableOpacity
            style={[styles.primaryBtn, loading && styles.primaryBtnDisabled]}
            onPress={step === 'details' ? handleCreate : handleVerify}
            disabled={loading}
            activeOpacity={0.85}
          >
            {loading ? (
              <ActivityIndicator color={C.white} size="small" />
            ) : (
              <Text style={styles.primaryBtnText}>
                {step === 'details' ? 'Call to verify' : 'Confirm code'}
              </Text>
            )}
          </TouchableOpacity>

          {step === 'verify' ? (
            <TouchableOpacity
              onPress={() => {
                setStep('details');
                setError(null);
                setNotice(null);
              }}
              style={styles.backLink}
            >
              <Text style={styles.backText}>Change the number</Text>
            </TouchableOpacity>
          ) : null}
        </View>

        <TouchableOpacity onPress={handleSignOut} style={styles.signOutLink}>
          <Text style={styles.signOutText}>Sign out and use a different account</Text>
        </TouchableOpacity>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.cream },
  scroll: { padding: 24, paddingBottom: 60 },

  header: { alignItems: 'center', paddingVertical: 28 },
  wordmark: {
    fontFamily: 'Inter_700Bold',
    fontSize: 40,
    color: C.navy,
    letterSpacing: 6,
    marginBottom: 8,
  },
  greeting: { fontFamily: 'Inter_400Regular', fontSize: 16, color: C.muted },

  card: {
    backgroundColor: C.white,
    borderRadius: 24,
    padding: 28,
    shadowColor: C.navy,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 16,
    elevation: 6,
  },
  cardTitle: {
    fontFamily: 'Inter_700Bold',
    fontSize: 22,
    color: C.navy,
    marginBottom: 12,
  },
  cardBody: {
    fontFamily: 'Inter_400Regular',
    fontSize: 15,
    color: C.muted,
    lineHeight: 22,
    marginBottom: 18,
  },
  strong: { fontFamily: 'Inter_600SemiBold', color: C.navy },

  label: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 13,
    color: C.navy,
    marginBottom: 6,
  },
  input: {
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 13,
    fontFamily: 'Inter_400Regular',
    fontSize: 16,
    color: C.navy,
    backgroundColor: C.cream,
    marginBottom: 6,
  },
  codeInput: {
    fontFamily: 'Inter_700Bold',
    fontSize: 24,
    letterSpacing: 8,
    textAlign: 'center',
  },
  hint: {
    fontFamily: 'Inter_400Regular',
    fontSize: 12,
    color: C.muted,
    lineHeight: 17,
    marginBottom: 16,
  },

  resendLink: { paddingVertical: 12, alignItems: 'center' },
  resendText: {
    fontFamily: 'Inter_500Medium',
    fontSize: 13,
    color: C.blue,
    textDecorationLine: 'underline',
  },
  resendMuted: { color: C.muted, textDecorationLine: 'none' },

  errBanner: {
    backgroundColor: C.errBg,
    borderRadius: 10,
    padding: 12,
    marginBottom: 16,
    borderLeftWidth: 3,
    borderLeftColor: C.err,
  },
  errText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.err },

  okBanner: {
    backgroundColor: C.okBg,
    borderRadius: 10,
    padding: 12,
    marginBottom: 16,
    borderLeftWidth: 3,
    borderLeftColor: C.ok,
  },
  okText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.ok },

  primaryBtn: {
    backgroundColor: C.blue,
    borderRadius: 14,
    paddingVertical: 18,
    alignItems: 'center',
    marginTop: 4,
  },
  primaryBtnDisabled: { opacity: 0.6 },
  primaryBtnText: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 17,
    color: C.white,
  },

  backLink: { alignItems: 'center', paddingTop: 16 },
  backText: {
    fontFamily: 'Inter_400Regular',
    fontSize: 13,
    color: C.muted,
    textDecorationLine: 'underline',
  },

  signOutLink: { alignItems: 'center', paddingVertical: 24 },
  signOutText: {
    fontFamily: 'Inter_400Regular',
    fontSize: 13,
    color: C.muted,
    textDecorationLine: 'underline',
  },
});
