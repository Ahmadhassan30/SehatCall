import React, { useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { authClient } from '@/lib/auth-client';
import { useDawa } from '@/context/DawaContext';
import { useLanguage, type AppLanguage } from '@/context/LanguageContext';
import { radius, ui } from '@/lib/ui';

function LanguageSwitch() {
  const { language, setLanguage } = useLanguage();
  const options: Array<{ value: AppLanguage; label: string }> = [
    { value: 'en', label: 'English' },
    { value: 'ur', label: 'اردو' },
  ];

  return (
    <View style={styles.languageSwitch}>
      {options.map((option) => (
        <TouchableOpacity
          key={option.value}
          style={[styles.languageOption, language === option.value && styles.languageOptionActive]}
          onPress={() => setLanguage(option.value)}
        >
          <Text style={[styles.languageText, language === option.value && styles.languageTextActive]}>
            {option.label}
          </Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

export default function SignInScreen() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const { apiBaseUrl } = useDawa();
  const { t, isUrdu } = useLanguage();
  const rtl = isUrdu && styles.rtlText;

  const handleGoogleSignIn = async () => {
    if (!apiBaseUrl) {
      setError(t('signin.backendMissing'));
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await authClient.signIn.social({ provider: 'google', callbackURL: '/' });
      router.replace('/');
    } catch (e) {
      setError(e instanceof Error ? e.message : t('signin.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <View style={styles.topRow}>
        <Text style={styles.wordmark}>DAWA</Text>
        <LanguageSwitch />
      </View>

      <View style={styles.content}>
        <Text style={[styles.tagline, rtl]}>{t('signin.tagline')}</Text>
      </View>

      <View style={styles.authPanel}>
        <Text style={[styles.title, rtl]}>{t('signin.title')}</Text>
        <Text style={[styles.body, rtl]}>{t('signin.body')}</Text>

        {error ? (
          <View style={styles.errorBox}>
            <Text style={[styles.errorText, rtl]}>{error}</Text>
          </View>
        ) : null}

        <TouchableOpacity
          style={[styles.googleButton, loading && styles.disabled]}
          onPress={handleGoogleSignIn}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color={ui.text} size="small" />
          ) : (
            <>
              <Text style={styles.googleMark}>G</Text>
              <Text style={[styles.googleText, isUrdu && styles.urduFont]}>{t('signin.google')}</Text>
            </>
          )}
        </TouchableOpacity>
        <Text style={[styles.privacy, rtl]}>{t('signin.privacy')}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: ui.canvas,
    paddingHorizontal: 24,
    paddingTop: 64,
    paddingBottom: 36,
  },
  topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  wordmark: {
    fontFamily: 'Inter_700Bold',
    fontSize: 32,
    color: ui.text,
    letterSpacing: 0,
  },
  languageSwitch: {
    flexDirection: 'row',
    borderWidth: 1,
    borderColor: ui.line,
    borderRadius: radius.medium,
    padding: 2,
    backgroundColor: ui.surface,
  },
  languageOption: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.small },
  languageOptionActive: { backgroundColor: ui.primarySoft },
  languageText: { fontSize: 12, color: ui.muted },
  languageTextActive: { color: ui.primary, fontFamily: 'Inter_600SemiBold' },
  content: { flex: 1, justifyContent: 'center' },
  tagline: {
    maxWidth: 330,
    fontFamily: 'Inter_700Bold',
    fontSize: 34,
    lineHeight: 43,
    color: ui.text,
    letterSpacing: 0,
  },
  authPanel: { borderTopWidth: 1, borderTopColor: ui.line, paddingTop: 24 },
  title: { fontFamily: 'Inter_700Bold', fontSize: 24, color: ui.text, marginBottom: 8 },
  body: { fontFamily: 'Inter_400Regular', fontSize: 16, lineHeight: 24, color: ui.muted, marginBottom: 22 },
  googleButton: {
    height: 54,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: ui.surface,
    borderWidth: 1,
    borderColor: ui.line,
    borderRadius: radius.medium,
  },
  googleMark: { fontFamily: 'Inter_700Bold', fontSize: 17, color: '#356AC3' },
  googleText: { fontFamily: 'Inter_600SemiBold', fontSize: 16, color: ui.text },
  privacy: { fontFamily: 'Inter_400Regular', fontSize: 12, lineHeight: 18, color: ui.muted, marginTop: 14, textAlign: 'center' },
  errorBox: { backgroundColor: ui.dangerSoft, borderRadius: radius.medium, padding: 12, marginBottom: 14 },
  errorText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.danger },
  disabled: { opacity: 0.55 },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
  urduFont: { fontFamily: undefined },
});
