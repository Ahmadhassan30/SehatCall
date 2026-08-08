import React from 'react';
import { View, Text, StyleSheet, StatusBar } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

const C = {
  cream: '#F7F3E8',
  navy: '#243642',
  blue: '#6F9FB5',
};

interface Props {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}

export function DawaHeader({ title, subtitle, right }: Props) {
  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <StatusBar barStyle="dark-content" backgroundColor={C.cream} />
      <View style={styles.row}>
        <View style={styles.text}>
          <Text style={styles.title}>{title}</Text>
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        </View>
        {right ? <View>{right}</View> : null}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { backgroundColor: C.cream },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#D8D0BC',
  },
  text: { flex: 1 },
  title: {
    fontFamily: 'Inter_700Bold',
    fontSize: 22,
    color: C.navy,
    letterSpacing: -0.4,
  },
  subtitle: {
    fontFamily: 'Inter_400Regular',
    fontSize: 13,
    color: C.navy + '99',
    marginTop: 2,
  },
});
