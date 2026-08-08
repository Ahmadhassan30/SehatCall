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

export default function Root() {
  const { data: session, isPending } = authClient.useSession();
  const { patient, patientLoading, patientReady, patientError, refreshPatient } = useP3();
  const { apiBaseUrl } = useDawa();
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
        <Text style={styles.errorTitle}>Couldn&apos;t load your patient</Text>
        <Text style={styles.errorText}>{patientError}</Text>
        <TouchableOpacity style={styles.retryButton} onPress={refreshPatient}>
          <Text style={styles.retryText}>Try again</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <ActivityIndicator size="large" color="#6F9FB5" />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: '#F7F3E8',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 28,
  },
  errorTitle: {
    fontFamily: 'Inter_700Bold',
    fontSize: 20,
    color: '#243642',
    marginBottom: 10,
    textAlign: 'center',
  },
  errorText: {
    fontFamily: 'Inter_400Regular',
    fontSize: 14,
    lineHeight: 20,
    color: '#7A8A8E',
    marginBottom: 20,
    textAlign: 'center',
  },
  retryButton: {
    backgroundColor: '#6F9FB5',
    borderRadius: 8,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  retryText: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 15,
    color: '#FFFFFF',
  },
});
