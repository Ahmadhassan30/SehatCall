/**
 * DAWA Caregiver — Sign In
 *
 * Initiates Google OAuth via the TypeScript API server (Better Auth).
 * The session cookie is stored in SecureStore by the @better-auth/expo plugin.
 *
 * After sign-in the user is redirected back to app/index.tsx which routes
 * them to onboarding (if no patient claimed) or to the main tabs.
 */
import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Image,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { authClient } from '@/lib/auth-client';
import { useDawa } from '@/context/DawaContext';

const C = {
  cream: '#F7F3E8',
  blue: '#6F9FB5',
  navy: '#243642',
  white: '#FFFFFF',
  muted: '#7A8A8E',
  border: '#D8D0BC',
  err: '#B83232',
  errBg: '#FDEAEA',
};

export default function SignInScreen() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const { apiBaseUrl } = useDawa();

  const handleGoogleSignIn = async () => {
    if (!apiBaseUrl) {
      setError('Backend URL not set. Go to Settings and configure the API URL first.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await authClient.signIn.social({
        provider: 'google',
        // The Expo plugin turns this into a deep link via Linking.createURL(),
        // so it MUST name a route that actually exists. "(auth)" is a route
        // group — the parentheses contribute nothing to the URL — so paths like
        // "/auth/callback" resolve to +not-found. Land on "/" (app/index.tsx),
        // which is the session-gated router and sends the caregiver on to
        // onboarding or the tabs once the session is readable.
        callbackURL: '/',
      });
      // Belt and braces: if the browser session closes without firing the deep
      // link, this still moves us off the sign-in screen.
      router.replace('/');
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Sign in failed. Check your connection and try again.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />

      <View style={styles.hero}>
        <Text style={styles.wordmark}>DAWA</Text>
        <Text style={styles.tagline}>
          Urdu medication reminders for{'\n'}people who matter most.
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Welcome, caregiver</Text>
        <Text style={styles.cardBody}>
          Sign in to access your patient's medication schedule, call history, and
          voice settings.
        </Text>

        {error ? (
          <View style={styles.errBanner}>
            <Text style={styles.errText}>{error}</Text>
          </View>
        ) : null}

        <TouchableOpacity
          style={[styles.googleBtn, loading && styles.googleBtnDisabled]}
          onPress={handleGoogleSignIn}
          disabled={loading}
          activeOpacity={0.85}
        >
          {loading ? (
            <ActivityIndicator color={C.navy} size="small" />
          ) : (
            <>
              <Text style={styles.googleBtnIcon}>G</Text>
              <Text style={styles.googleBtnText}>Continue with Google</Text>
            </>
          )}
        </TouchableOpacity>

        <Text style={styles.disclaimer}>
          DAWA uses Google OAuth to identify caregivers. No data is shared with Google
          beyond your account email and name.
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: C.cream,
    justifyContent: 'space-between',
    paddingHorizontal: 24,
    paddingTop: 80,
    paddingBottom: 48,
  },

  hero: {
    alignItems: 'center',
    paddingTop: 20,
  },
  wordmark: {
    fontFamily: 'Inter_700Bold',
    fontSize: 64,
    color: C.navy,
    letterSpacing: 8,
    marginBottom: 16,
  },
  tagline: {
    fontFamily: 'Inter_400Regular',
    fontSize: 18,
    color: C.muted,
    textAlign: 'center',
    lineHeight: 26,
  },

  card: {
    backgroundColor: C.white,
    borderRadius: 24,
    padding: 28,
    shadowColor: C.navy,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.10,
    shadowRadius: 16,
    elevation: 6,
  },
  cardTitle: {
    fontFamily: 'Inter_700Bold',
    fontSize: 24,
    color: C.navy,
    marginBottom: 10,
  },
  cardBody: {
    fontFamily: 'Inter_400Regular',
    fontSize: 15,
    color: C.muted,
    lineHeight: 22,
    marginBottom: 24,
  },

  errBanner: {
    backgroundColor: C.errBg,
    borderRadius: 10,
    padding: 12,
    marginBottom: 16,
    borderLeftWidth: 3,
    borderLeftColor: C.err,
  },
  errText: {
    fontFamily: 'Inter_400Regular',
    fontSize: 13,
    color: C.err,
  },

  googleBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    backgroundColor: C.white,
    borderWidth: 1.5,
    borderColor: C.border,
    borderRadius: 14,
    paddingVertical: 16,
    paddingHorizontal: 20,
    shadowColor: C.navy,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 6,
    elevation: 2,
  },
  googleBtnDisabled: { opacity: 0.6 },
  googleBtnIcon: {
    fontFamily: 'Inter_700Bold',
    fontSize: 18,
    color: '#4285F4',
  },
  googleBtnText: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 16,
    color: C.navy,
  },

  disclaimer: {
    fontFamily: 'Inter_400Regular',
    fontSize: 11,
    color: C.muted,
    textAlign: 'center',
    lineHeight: 16,
    marginTop: 20,
  },
});
