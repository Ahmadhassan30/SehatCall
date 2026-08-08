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
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { authClient } from '@/lib/auth-client';
import { useP3 } from '@/context/P3Context';
import { useDawa } from '@/context/DawaContext';

export default function Root() {
  const { data: session, isPending } = authClient.useSession();
  const { patient, patientLoading } = useP3();
  const { apiBaseUrl } = useDawa();
  const router = useRouter();

  useEffect(() => {
    if (isPending) return;

    if (!session) {
      router.replace('/(auth)/sign-in');
      return;
    }

    // Session is valid — wait for P3Context to finish loading if a URL is set
    if (apiBaseUrl && patientLoading) return;

    if (!patient || !patient.phoneVerified) {
      // Either apiBaseUrl is not set (Settings first), no patient exists yet,
      // or the phone number still needs verifying.
      router.replace('/(auth)/onboarding');
      return;
    }

    router.replace('/(tabs)');
  }, [session, isPending, patient, patientLoading, apiBaseUrl]);

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
  },
});
