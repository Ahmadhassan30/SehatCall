import { Link, Stack } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { StyleSheet, Text, View } from 'react-native';
import { useLanguage } from '@/context/LanguageContext';
import { radius, ui } from '@/lib/ui';

export default function NotFoundScreen() {
  const { isUrdu, t } = useLanguage();
  return (
    <>
      <Stack.Screen options={{ title: t('notFound.title') }} />
      <View style={styles.container}>
        <Ionicons name="document-outline" size={30} color={ui.muted} />
        <Text style={[styles.title, isUrdu && styles.rtlText]}>{t('notFound.title')}</Text>
        <Link href="/" style={styles.link}>
          <Text style={[styles.linkText, isUrdu && styles.rtlText]}>{t('notFound.home')}</Text>
        </Link>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: ui.canvas },
  title: { fontFamily: 'Inter_700Bold', fontSize: 24, color: ui.text, marginTop: 14 },
  link: { marginTop: 18, backgroundColor: ui.primary, borderRadius: radius.medium, paddingHorizontal: 18, paddingVertical: 12 },
  linkText: { fontFamily: 'Inter_700Bold', fontSize: 15, color: ui.surface },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});
