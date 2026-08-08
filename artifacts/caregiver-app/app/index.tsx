/**
 * Entry point — routes to sign-in, onboarding, or the main tabs based on
 * the caregiver's auth session and whether they have claimed a demo patient.
 *
 * Routing logic:
 *   1. isPending             → show loading screen (session not yet resolved)
 *   2. !session              → /(auth)/sign-in
 *   3. session, no patient   → /(auth)/onboarding  (set the patient up first)
 *   4. session, unverified   → /(auth)/onboarding  (finish proving the number)
 *   5. session, verified     → /(tabs)
 *
 * An unverified number is treated exactly like no patient at all: the main app
 * is built around calls, and DAWA will not place one until the number is proved.
 */
import React, { useEffect } from 'react';
import { View, Text, TouchableOpacity, ActivityIndicator, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { authClient } from '@/lib/auth-client';
import { useP3 } from '@/context/P3Context';
import { useDawa } from '@/context/DawaContext';
import { useLanguage } from '@/context/LanguageContext';
import { radius, ui } from '@/lib/ui';

export default function Root() {
  const { data: session, isPending } = authClient.useSession();
  const { patient, patientLoading, patientReady, patientError, refreshPatient } = useP3();
  const { apiBaseUrl } = useDawa();
  const { isUrdu, t } = useLanguage();
  const router = useRouter();

  useEffect(() => {
    if (isPending) return;

    if (!session) {
      router.replace('/(auth)/sign-in');
      return;
    }

    // Wait for the lookup tied to this authenticated user. An earlier
    // unauthenticated 401 must never be mistaken for "no patient".
    if (apiBaseUrl && (!patientReady || patientLoading)) return;

    // A failed lookup is not evidence that setup is missing. Stay here and
    // offer retry instead of sending an existing caregiver through onboarding.
    if (patientError) return;

    if (!patient || !patient.phoneVerified) {
      // Either apiBaseUrl is not set (Settings first), no patient exists yet,
      // or the phone number still needs verifying.
      router.replace('/(auth)/onboarding');
      return;
    }

    router.replace('/(tabs)');
  }, [session, isPending, patient, patientLoading, patientReady, patientError, apiBaseUrl]);

  if (session && patientReady && patientError) {
    return (
      <View style={styles.screen}>
        <Text style={[styles.errorTitle, isUrdu && styles.rtlText]}>{t('common.patientLoadFailed')}</Text>
        <Text style={[styles.errorText, isUrdu && styles.rtlText]}>{patientError}</Text>
        <TouchableOpacity style={styles.retryButton} onPress={refreshPatient}>
          <Text style={[styles.retryText, isUrdu && styles.rtlText]}>{t('common.retry')}</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <ActivityIndicator size="large" color={ui.primary} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: ui.canvas,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 28,
  },
  errorTitle: {
    fontFamily: 'Inter_700Bold',
    fontSize: 24,
    color: ui.text,
    marginBottom: 10,
    textAlign: 'center',
  },
  errorText: {
    fontFamily: 'Inter_400Regular',
    fontSize: 15,
    lineHeight: 23,
    color: ui.muted,
    marginBottom: 20,
    textAlign: 'center',
  },
  retryButton: {
    backgroundColor: ui.primary,
    borderRadius: radius.medium,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  retryText: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 16,
    color: ui.surface,
  },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});
