import React from 'react';
import { View, Text, StyleSheet, StatusBar } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLanguage } from '@/context/LanguageContext';
import { ui } from '@/lib/ui';

interface Props {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}

export function DawaHeader({ title, subtitle, right }: Props) {
  const { isUrdu } = useLanguage();
  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <StatusBar barStyle="dark-content" backgroundColor={ui.surface} />
      <View style={[styles.row, isUrdu && styles.rowRtl]}>
        <View style={styles.text}>
          <Text style={[styles.title, isUrdu && styles.urduText]}>{title}</Text>
          {subtitle ? <Text style={[styles.subtitle, isUrdu && styles.urduText]}>{subtitle}</Text> : null}
        </View>
        {right ? <View>{right}</View> : null}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { backgroundColor: ui.surface },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: ui.line,
  },
  rowRtl: { flexDirection: 'row-reverse' },
  text: { flex: 1 },
  title: {
    fontFamily: 'Inter_700Bold',
    fontSize: 28,
    color: ui.text,
    letterSpacing: 0,
  },
  subtitle: {
    fontFamily: 'Inter_500Medium',
    fontSize: 14,
    color: ui.muted,
    marginTop: 4,
  },
  urduText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});
