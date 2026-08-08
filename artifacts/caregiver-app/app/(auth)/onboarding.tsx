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
import { useLanguage } from '@/context/LanguageContext';
import { radius, ui } from '@/lib/ui';

const C = {
  cream: ui.canvas,
  blue: ui.primary,
  navy: ui.text,
  white: ui.surface,
  muted: ui.muted,
  border: ui.line,
  err: ui.danger,
  errBg: ui.dangerSoft,
  ok: ui.success,
  okBg: ui.successSoft,
};

type Step = 'details' | 'verify';

export default function OnboardingScreen() {
  const router = useRouter();
  const { apiBaseUrl } = useDawa();
  const { data: session } = authClient.useSession();
  const { t, isUrdu } = useLanguage();
  const rtl = isUrdu && styles.rtlText;
  const {
    patient,
    patientLoading,
    patientReady,
    patientError,
    refreshPatient,
    createPatient,
    updatePatient,
    sendPhoneCode,
    verifyPhoneCode,
  } = useP3();

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
    if (patient.phoneVerified) {
      router.replace('/(tabs)');
      return;
    }
    setName((v) => v || patient.name);
    setAddress((v) => v || patient.preferredAddress);
    if (!patient.phoneVerified && patient.phoneVerificationInProgress && patient.maskedPhone) {
      setMaskedPhone(patient.maskedPhone);
      setStep('verify');
    }
  }, [patient, router]);

  // Resend cooldown ticker.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const requireApi = (): boolean => {
    if (!apiBaseUrl) {
      setError(t('onboarding.backendMissing'));
      return false;
    }
    return true;
  };

  const describe = (e: unknown) =>
    e instanceof Error ? e.message : t('onboarding.failed');

  const handleCreate = async () => {
    if (!requireApi()) return;
    if (!name.trim() || !address.trim() || !phone.trim()) {
      setError(t('onboarding.completeFields'));
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
      setNotice(t('onboarding.callingAgain'));
    } catch (e) {
      setError(describe(e));
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    if (!requireApi()) return;
    if (!code.trim()) {
      setError(t('onboarding.enterCode'));
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

  // Never flash setup while resolving this account or while leaving for the
  // main app with an already-verified patient.
  if (!patientReady || patientLoading || patient?.phoneVerified) {
    return (
      <View style={[styles.screen, styles.loadingScreen]}>
        <StatusBar style="dark" />
        <ActivityIndicator size="large" color={C.blue} />
      </View>
    );
  }

  if (patientError) {
    return (
      <View style={[styles.screen, styles.loadingScreen]}>
        <StatusBar style="dark" />
        <Text style={[styles.lookupErrorTitle, rtl]}>{t('common.patientLoadFailed')}</Text>
        <Text style={[styles.lookupErrorText, rtl]}>{patientError}</Text>
        <TouchableOpacity style={styles.lookupRetryButton} onPress={refreshPatient}>
          <Text style={[styles.lookupRetryText, isUrdu && styles.urduFont]}>{t('common.retry')}</Text>
        </TouchableOpacity>
      </View>
    );
  }

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
            <Text style={[styles.greeting, rtl]}>
              {t('onboarding.greeting', { name: session.user.name.split(' ')[0] })}
            </Text>
          ) : null}
        </View>

        <View style={styles.card}>
          {step === 'details' ? (
            <>
              <Text style={[styles.cardTitle, rtl]}>{t('onboarding.who')}</Text>
              <Text style={[styles.cardBody, rtl]}>{t('onboarding.whoBody')}</Text>

              <Text style={[styles.label, rtl]}>{t('onboarding.name')}</Text>
              <TextInput
                style={[styles.input, isUrdu && styles.rtlInput]}
                value={name}
                onChangeText={setName}
                placeholder={t('onboarding.nameExample')}
                placeholderTextColor={C.muted}
                autoCapitalize="words"
                editable={!loading}
              />

              <Text style={[styles.label, rtl]}>{t('onboarding.address')}</Text>
              <TextInput
                style={[styles.input, isUrdu && styles.rtlInput]}
                value={address}
                onChangeText={setAddress}
                placeholder={t('onboarding.addressExample')}
                placeholderTextColor={C.muted}
                autoCapitalize="words"
                editable={!loading}
              />
              <Text style={[styles.hint, rtl]}>{t('onboarding.addressHint')}</Text>

              <Text style={[styles.label, rtl]}>{t('onboarding.phone')}</Text>
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
              <Text style={[styles.hint, rtl]}>{t('onboarding.phoneHint')}</Text>
            </>
          ) : (
            <>
              <Text style={[styles.cardTitle, rtl]}>{t('onboarding.checkPhone')}</Text>
              <Text style={[styles.cardBody, rtl]}>
                {t('onboarding.codeBody', { phone: maskedPhone ?? '' })}
              </Text>

              <Text style={[styles.label, rtl]}>{t('onboarding.code')}</Text>
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
                  {cooldown > 0
                    ? t('onboarding.resendIn', { seconds: cooldown })
                    : t('onboarding.resend')}
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
                {step === 'details' ? t('onboarding.callVerify') : t('onboarding.confirm')}
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
              <Text style={[styles.backText, isUrdu && styles.urduFont]}>{t('onboarding.changeNumber')}</Text>
            </TouchableOpacity>
          ) : null}
        </View>

        <TouchableOpacity onPress={handleSignOut} style={styles.signOutLink}>
          <Text style={[styles.signOutText, isUrdu && styles.urduFont]}>{t('onboarding.signOut')}</Text>
        </TouchableOpacity>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.cream },
  loadingScreen: { alignItems: 'center', justifyContent: 'center' },
  lookupErrorTitle: {
    fontFamily: 'Inter_700Bold',
    fontSize: 20,
    color: C.navy,
    marginBottom: 10,
  },
  lookupErrorText: {
    fontFamily: 'Inter_400Regular',
    fontSize: 14,
    lineHeight: 20,
    color: C.muted,
    marginBottom: 20,
    paddingHorizontal: 28,
    textAlign: 'center',
  },
  lookupRetryButton: {
    backgroundColor: C.blue,
    borderRadius: 8,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  lookupRetryText: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 15,
    color: C.white,
  },
  scroll: { padding: 24, paddingBottom: 60 },

  header: { alignItems: 'center', paddingVertical: 28 },
  wordmark: {
    fontFamily: 'Inter_700Bold',
    fontSize: 32,
    color: C.navy,
    letterSpacing: 0,
    marginBottom: 8,
  },
  greeting: { fontFamily: 'Inter_500Medium', fontSize: 16, color: C.muted },

  card: {
    backgroundColor: C.white,
    borderRadius: radius.large,
    padding: 22,
    borderWidth: 1,
    borderColor: C.border,
  },
  cardTitle: {
    fontFamily: 'Inter_700Bold',
    fontSize: 26,
    color: C.navy,
    marginBottom: 12,
  },
  cardBody: {
    fontFamily: 'Inter_400Regular',
    fontSize: 16,
    color: C.muted,
    lineHeight: 24,
    marginBottom: 18,
  },
  strong: { fontFamily: 'Inter_600SemiBold', color: C.navy },

  label: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 14,
    color: C.navy,
    marginBottom: 6,
  },
  input: {
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: radius.medium,
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
    letterSpacing: 0,
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
    borderRadius: radius.medium,
    padding: 12,
    marginBottom: 16,
    borderLeftWidth: 3,
    borderLeftColor: C.err,
  },
  errText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.err },

  okBanner: {
    backgroundColor: C.okBg,
    borderRadius: radius.medium,
    padding: 12,
    marginBottom: 16,
    borderLeftWidth: 3,
    borderLeftColor: C.ok,
  },
  okText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.ok },

  primaryBtn: {
    backgroundColor: C.blue,
    borderRadius: radius.medium,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 4,
  },
  primaryBtnDisabled: { opacity: 0.6 },
  primaryBtnText: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 18,
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
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
  rtlInput: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
  urduFont: { fontFamily: undefined },
});
