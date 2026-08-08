/**
 * Calls tab — history of dose call events.
 *
 * SAFETY: callStatus and adherenceOutcome are ALWAYS shown separately.
 * A "completed" call NEVER implies the medicine was taken. When adherenceOutcome
 * is null we show the server's adherenceLabel ("Outcome not confirmed") verbatim.
 */
import React, { useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  RefreshControl,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useP3, type P3Call } from '@/context/P3Context';
import { DawaHeader } from '@/components/DawaHeader';

const C = {
  cream: '#F7F3E8',
  blue: '#6F9FB5',
  navy: '#243642',
  white: '#FFFFFF',
  border: '#D8D0BC',
  muted: '#7A8A8E',
  warn: '#C97B2A',
  warnBg: '#FDF3E3',
  err: '#B83232',
  errBg: '#FDEAEA',
  ok: '#2D7A4F',
  okBg: '#EAF5EE',
};

const CALL_STATUS_CONFIG: Record<string, { bg: string; fg: string; label: string }> = {
  completed:  { bg: '#EEF4F0', fg: '#2D7A4F', label: 'Completed' },
  answered:   { bg: '#EEF4F0', fg: '#2D7A4F', label: 'Answered' },
  failed:     { bg: C.errBg,   fg: C.err,     label: 'Not connected' },
  calling:    { bg: C.warnBg,  fg: C.warn,    label: 'Calling' },
  dispatched: { bg: C.warnBg,  fg: C.warn,    label: 'Dispatched' },
  ringing:    { bg: C.warnBg,  fg: C.warn,    label: 'Ringing' },
  scheduled:  { bg: '#F0F4F8', fg: C.muted,   label: 'Scheduled' },
};

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-PK', { month: 'short', day: 'numeric' }) +
      ' ' + d.toLocaleTimeString('en-PK', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

function CallRow({ item }: { item: P3Call }) {
  const statusCfg = CALL_STATUS_CONFIG[item.callStatus] ??
    { bg: '#F0F0F0', fg: C.muted, label: item.callStatus };

  return (
    <View style={styles.row}>
      <View style={styles.rowTop}>
        <Text style={styles.medName} numberOfLines={1}>
          {item.nickname || item.clinicalName || 'Medication'}
        </Text>
        <View style={[styles.badge, { backgroundColor: statusCfg.bg }]}>
          <Text style={[styles.badgeText, { color: statusCfg.fg }]}>{statusCfg.label}</Text>
        </View>
      </View>

      <Text style={styles.time}>{formatDateTime(item.scheduledTime)}</Text>

      {/* Adherence ALWAYS shown separately — never inferred from callStatus */}
      <View style={styles.adherenceRow}>
        <View style={styles.adherencePill}>
          <Text style={styles.adherenceLabel}>Adherence: </Text>
          <Text style={[
            styles.adherenceValue,
            item.adherenceOutcome === 'TAKEN' && styles.taken,
            item.adherenceOutcome === 'NOT_TAKEN' && styles.notTaken,
          ]}>
            {item.adherenceLabel}
          </Text>
        </View>
      </View>
    </View>
  );
}

export default function CallsScreen() {
  const { calls, callsLoading, callsError, refreshCalls } = useP3();

  const onRefresh = useCallback(() => refreshCalls(), [refreshCalls]);

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <DawaHeader
        title="Call History"
        subtitle={calls.length > 0 ? `${calls.length} calls` : undefined}
      />
      <FlatList
        data={calls}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <CallRow item={item} />}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={() => <View style={styles.sep} />}
        refreshControl={
          <RefreshControl
            refreshing={callsLoading}
            onRefresh={onRefresh}
            tintColor={C.blue}
          />
        }
        ListEmptyComponent={
          callsError ? (
            <View style={styles.emptyWrap}>
              <Text style={styles.emptyTitle}>Could not load calls</Text>
              <Text style={styles.emptyText}>{callsError}</Text>
              <TouchableOpacity style={styles.retryBtn} onPress={onRefresh}>
                <Text style={styles.retryText}>Try again</Text>
              </TouchableOpacity>
            </View>
          ) : !callsLoading ? (
            <View style={styles.emptyWrap}>
              <Text style={styles.emptyTitle}>No calls yet</Text>
              <Text style={styles.emptyText}>
                DAWA will log every reminder call here. The outcome is only updated when the call ends and the patient responds.
              </Text>
            </View>
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.cream },
  list: { padding: 16, paddingBottom: 40 },
  sep: { height: 8 },

  row: {
    backgroundColor: C.white,
    borderRadius: 14,
    padding: 16,
    shadowColor: C.navy,
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  medName: { fontFamily: 'Inter_600SemiBold', fontSize: 16, color: C.navy, flex: 1, marginRight: 8 },
  time: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted, marginBottom: 10 },

  badge: { borderRadius: 8, paddingHorizontal: 10, paddingVertical: 4, flexShrink: 0 },
  badgeText: { fontFamily: 'Inter_600SemiBold', fontSize: 12 },

  adherenceRow: { borderTopWidth: 1, borderTopColor: C.border + '60', paddingTop: 10, marginTop: 2 },
  adherencePill: { flexDirection: 'row', alignItems: 'center' },
  adherenceLabel: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted },
  adherenceValue: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.navy },
  taken: { color: '#2D7A4F' },
  notTaken: { color: C.err },

  emptyWrap: { padding: 32, alignItems: 'center' },
  emptyTitle: { fontFamily: 'Inter_600SemiBold', fontSize: 17, color: C.navy, marginBottom: 8 },
  emptyText: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.muted, textAlign: 'center', lineHeight: 21, marginBottom: 16 },
  retryBtn: { paddingHorizontal: 20, paddingVertical: 10, backgroundColor: C.blue, borderRadius: 10 },
  retryText: { fontFamily: 'Inter_600SemiBold', fontSize: 14, color: '#FFF' },
});
