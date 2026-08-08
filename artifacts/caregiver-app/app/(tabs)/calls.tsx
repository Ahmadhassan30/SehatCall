import React, { useCallback } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { Ionicons } from '@expo/vector-icons';
import { DawaHeader } from '@/components/DawaHeader';
import { useLanguage } from '@/context/LanguageContext';
import { useP3, type P3Call } from '@/context/P3Context';
import { radius, ui } from '@/lib/ui';

function adherenceKey(outcome: string | null): string {
  if (outcome === 'TAKEN') return 'adherence.taken';
  if (outcome === 'NOT_TAKEN') return 'adherence.notTaken';
  return 'adherence.unknown';
}

function CallRow({ item }: { item: P3Call }) {
  const { isUrdu, language, t } = useLanguage();
  const successful = item.callStatus === 'completed' || item.callStatus === 'answered';
  const failed = item.callStatus === 'failed';
  const tone = successful
    ? { bg: ui.successSoft, fg: ui.success }
    : failed
      ? { bg: ui.dangerSoft, fg: ui.danger }
      : { bg: ui.warningSoft, fg: ui.warning };
  const rtl = isUrdu ? styles.rtlText : undefined;
  const statusKey = `status.${item.callStatus}`;
  const translatedStatus = t(statusKey);

  const formatDateTime = (iso: string) => {
    try {
      const date = new Date(iso);
      return date.toLocaleString(language === 'ur' ? 'ur-PK' : 'en-PK', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  return (
    <View style={styles.card}>
      <View style={[styles.topRow, isUrdu && styles.rowRtl]}>
        <View style={styles.medInfo}>
          <Text style={[styles.medName, rtl]} numberOfLines={1}>
            {item.nickname || item.clinicalName || t('calls.medication')}
          </Text>
          <Text style={[styles.time, rtl]}>{formatDateTime(item.scheduledTime)}</Text>
        </View>
        <View style={[styles.badge, { backgroundColor: tone.bg }]}>
          <Text style={[styles.badgeText, { color: tone.fg }, rtl]}>
            {translatedStatus === statusKey ? item.callStatus : translatedStatus}
          </Text>
        </View>
      </View>

      <View style={[styles.outcomeRow, isUrdu && styles.rowRtl]}>
        <Text style={[styles.outcomeLabel, rtl]}>{t('calls.adherence')}</Text>
        <Text
          style={[
            styles.outcomeValue,
            item.adherenceOutcome === 'TAKEN' && styles.taken,
            item.adherenceOutcome === 'NOT_TAKEN' && styles.notTaken,
            rtl,
          ]}
        >
          {t(adherenceKey(item.adherenceOutcome))}
        </Text>
      </View>
    </View>
  );
}

export default function CallsScreen() {
  const { calls, callsLoading, callsError, refreshCalls } = useP3();
  const { isUrdu, t } = useLanguage();
  const rtl = isUrdu ? styles.rtlText : undefined;
  const onRefresh = useCallback(() => refreshCalls(), [refreshCalls]);

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <DawaHeader
        title={t('calls.title')}
        subtitle={calls.length ? t('calls.count', { count: calls.length }) : undefined}
      />
      <FlatList
        data={calls}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <CallRow item={item} />}
        contentContainerStyle={[styles.list, calls.length === 0 && styles.emptyList]}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        refreshControl={<RefreshControl refreshing={callsLoading} onRefresh={onRefresh} tintColor={ui.primary} />}
        ListEmptyComponent={
          callsError ? (
            <View style={styles.emptyWrap}>
              <Ionicons name="cloud-offline-outline" size={28} color={ui.danger} />
              <Text style={[styles.emptyTitle, rtl]}>{t('calls.loadError')}</Text>
              <Text style={[styles.emptyText, rtl]}>{callsError}</Text>
              <TouchableOpacity style={styles.retryButton} onPress={onRefresh} accessibilityRole="button">
                <Text style={[styles.retryText, rtl]}>{t('common.retry')}</Text>
              </TouchableOpacity>
            </View>
          ) : !callsLoading ? (
            <View style={styles.emptyWrap}>
              <Ionicons name="call-outline" size={28} color={ui.muted} />
              <Text style={[styles.emptyTitle, rtl]}>{t('calls.empty')}</Text>
              <Text style={[styles.emptyText, rtl]}>{t('calls.emptyBody')}</Text>
            </View>
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: ui.canvas },
  list: { padding: 16, paddingBottom: 40 },
  emptyList: { flexGrow: 1, justifyContent: 'center' },
  separator: { height: 10 },
  card: { backgroundColor: ui.surface, borderRadius: radius.medium, borderWidth: 1, borderColor: ui.line, padding: 18 },
  topRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  rowRtl: { flexDirection: 'row-reverse' },
  medInfo: { flex: 1 },
  medName: { fontFamily: 'Inter_700Bold', fontSize: 19, lineHeight: 25, color: ui.text },
  time: { fontFamily: 'Inter_500Medium', fontSize: 14, color: ui.muted, marginTop: 5 },
  badge: { flexShrink: 0, borderRadius: radius.small, paddingHorizontal: 9, paddingVertical: 4 },
  badgeText: { fontFamily: 'Inter_700Bold', fontSize: 12 },
  outcomeRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, borderTopWidth: 1, borderTopColor: ui.line, paddingTop: 12, marginTop: 12 },
  outcomeLabel: { fontFamily: 'Inter_500Medium', fontSize: 14, color: ui.muted },
  outcomeValue: { flex: 1, fontFamily: 'Inter_700Bold', fontSize: 14, color: ui.text, textAlign: 'right' },
  taken: { color: ui.success },
  notTaken: { color: ui.danger },
  emptyWrap: { alignItems: 'center', paddingHorizontal: 28 },
  emptyTitle: { fontFamily: 'Inter_700Bold', fontSize: 21, color: ui.text, marginTop: 12 },
  emptyText: { fontFamily: 'Inter_400Regular', fontSize: 15, lineHeight: 23, color: ui.muted, textAlign: 'center', marginTop: 7, maxWidth: 320 },
  retryButton: { backgroundColor: ui.primary, borderRadius: radius.medium, paddingHorizontal: 18, paddingVertical: 11, marginTop: 18 },
  retryText: { fontFamily: 'Inter_700Bold', fontSize: 15, color: ui.surface },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});
