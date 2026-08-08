/**
 * Medications tab — list, toggle active/auto-call, and navigate to add/edit.
 */
import React, { useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Switch,
  RefreshControl,
  Alert,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { useP3, type P3Medication } from '@/context/P3Context';
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
  inactiveBg: '#F5F0E8',
};

const CUE_LABELS: Record<string, string> = {
  package_color: 'Package',
  stripe_color: 'Stripe',
  tablet_shape: 'Shape',
  storage_location: 'Stored',
};

function MedCard({ med, onEdit, onToggleActive, onToggleAutoCall }: {
  med: P3Medication;
  onEdit: () => void;
  onToggleActive: (val: boolean) => void;
  onToggleAutoCall: (val: boolean) => void;
}) {
  const cueEntries = Object.entries(med.cues ?? {});

  return (
    <TouchableOpacity
      style={[styles.card, !med.active && styles.cardInactive]}
      onPress={onEdit}
      activeOpacity={0.85}
    >
      {/* Header row */}
      <View style={styles.cardHeader}>
        <View style={styles.cardTitleWrap}>
          <Text style={[styles.cardTitle, !med.active && styles.textMuted]}>
            {med.nickname || med.clinicalName}
          </Text>
          {med.nickname ? (
            <Text style={styles.cardSub}>{med.clinicalName}</Text>
          ) : null}
        </View>
        <Text style={styles.cardTime}>{med.scheduleTime}</Text>
      </View>

      <Text style={styles.cardDose}>{med.doseInstruction} · {med.dosage}</Text>

      {/* Visual cues — first-class, not hidden */}
      {cueEntries.length > 0 && (
        <View style={styles.cueRow}>
          {cueEntries.map(([k, v]) => (
            <View key={k} style={styles.cuePill}>
              <Text style={styles.cueLabel}>{CUE_LABELS[k] ?? k}: </Text>
              <Text style={styles.cueValue}>{v}</Text>
            </View>
          ))}
        </View>
      )}

      {/* Warnings from deterministic doctor-note conflict check */}
      {med.warnings?.map((w, i) => (
        <View key={i} style={styles.warnBanner}>
          <Text style={styles.warnText}>{w}</Text>
        </View>
      ))}

      {/* Doctor note */}
      {med.doctorInstructions ? (
        <View style={styles.docNote}>
          <Text style={styles.docNoteLabel}>
            Doctor{med.doctorName ? ` (${med.doctorName})` : ''}: 
          </Text>
          <Text style={styles.docNoteText}> {med.doctorInstructions}</Text>
        </View>
      ) : null}

      {/* Toggles */}
      <View style={styles.toggleRow}>
        <View style={styles.toggleItem}>
          <Text style={styles.toggleLabel}>Active</Text>
          <Switch
            value={med.active}
            onValueChange={onToggleActive}
            trackColor={{ true: C.blue, false: C.border }}
            thumbColor={C.white}
          />
        </View>
        <View style={styles.toggleItem}>
          <Text style={styles.toggleLabel}>Auto-call</Text>
          <Switch
            value={med.autoCallEnabled}
            onValueChange={onToggleAutoCall}
            disabled={!med.active}
            trackColor={{ true: C.blue, false: C.border }}
            thumbColor={C.white}
          />
        </View>
      </View>
    </TouchableOpacity>
  );
}

export default function MedicationsScreen() {
  const { medications, medicationsLoading, medicationsError, refreshMedications, updateMedication } = useP3();
  const router = useRouter();

  const onRefresh = useCallback(() => refreshMedications(), [refreshMedications]);

  const handleToggleActive = useCallback(
    async (med: P3Medication, val: boolean) => {
      try {
        await updateMedication(med.id, { active: val });
      } catch {
        Alert.alert('Could not update', 'Please try again.');
      }
    },
    [updateMedication]
  );

  const handleToggleAutoCall = useCallback(
    async (med: P3Medication, val: boolean) => {
      try {
        await updateMedication(med.id, { autoCallEnabled: val });
      } catch {
        Alert.alert('Could not update', 'Please try again.');
      }
    },
    [updateMedication]
  );

  const activeMeds = medications.filter((m) => m.active);
  const inactiveMeds = medications.filter((m) => !m.active);

  type Section = { type: 'header'; label: string; key: string } | { type: 'med'; item: P3Medication; key: string };
  const sections: Section[] = [];
  if (activeMeds.length > 0) {
    sections.push({ type: 'header', label: 'ACTIVE', key: 'h-active' });
    activeMeds.forEach((m) => sections.push({ type: 'med', item: m, key: m.id }));
  }
  if (inactiveMeds.length > 0) {
    sections.push({ type: 'header', label: 'INACTIVE', key: 'h-inactive' });
    inactiveMeds.forEach((m) => sections.push({ type: 'med', item: m, key: m.id }));
  }

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <DawaHeader
        title="Medications"
        right={
          <TouchableOpacity
            style={styles.addBtn}
            onPress={() => router.push('/medication/new')}
            activeOpacity={0.8}
          >
            <Text style={styles.addBtnText}>+ Add</Text>
          </TouchableOpacity>
        }
      />
      <FlatList
        data={sections}
        keyExtractor={(item) => item.key}
        renderItem={({ item }) => {
          if (item.type === 'header') {
            return <Text style={styles.groupLabel}>{item.label}</Text>;
          }
          const med = item.item;
          return (
            <MedCard
              med={med}
              onEdit={() => router.push(`/medication/${med.id}`)}
              onToggleActive={(v) => handleToggleActive(med, v)}
              onToggleAutoCall={(v) => handleToggleAutoCall(med, v)}
            />
          );
        }}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={() => <View style={{ height: 8 }} />}
        refreshControl={
          <RefreshControl
            refreshing={medicationsLoading}
            onRefresh={onRefresh}
            tintColor={C.blue}
          />
        }
        ListEmptyComponent={
          !medicationsLoading ? (
            <View style={styles.emptyWrap}>
              <Text style={styles.emptyTitle}>No medications yet</Text>
              <Text style={styles.emptyText}>
                Add Razia Bibi's medications so DAWA knows when to call and what to ask about.
              </Text>
              <TouchableOpacity
                style={styles.emptyBtn}
                onPress={() => router.push('/medication/new')}
              >
                <Text style={styles.emptyBtnText}>Add first medication</Text>
              </TouchableOpacity>
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
  groupLabel: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 11,
    color: C.muted,
    letterSpacing: 1.1,
    marginTop: 8,
    marginBottom: 6,
    paddingHorizontal: 4,
  },

  card: {
    backgroundColor: C.white,
    borderRadius: 16,
    padding: 18,
    shadowColor: C.navy,
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 6,
    elevation: 2,
  },
  cardInactive: { backgroundColor: C.inactiveBg, opacity: 0.75 },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 },
  cardTitleWrap: { flex: 1, marginRight: 8 },
  cardTitle: { fontFamily: 'Inter_700Bold', fontSize: 18, color: C.navy },
  cardSub: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted, marginTop: 2 },
  textMuted: { color: C.muted },
  cardTime: { fontFamily: 'Inter_600SemiBold', fontSize: 17, color: C.blue },
  cardDose: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.muted, marginBottom: 10 },

  cueRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 10 },
  cuePill: {
    flexDirection: 'row',
    backgroundColor: '#F0EBE0',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  cueLabel: { fontFamily: 'Inter_500Medium', fontSize: 12, color: C.muted },
  cueValue: { fontFamily: 'Inter_600SemiBold', fontSize: 12, color: C.navy },

  warnBanner: {
    backgroundColor: C.warnBg,
    borderRadius: 8,
    padding: 10,
    marginBottom: 8,
    borderLeftWidth: 3,
    borderLeftColor: C.warn,
  },
  warnText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.warn, lineHeight: 18 },

  docNote: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    backgroundColor: '#F5F0E8',
    borderRadius: 8,
    padding: 10,
    marginBottom: 10,
  },
  docNoteLabel: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.muted },
  docNoteText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.navy, flex: 1 },

  toggleRow: { flexDirection: 'row', borderTopWidth: 1, borderTopColor: C.border + '50', paddingTop: 14, marginTop: 4, gap: 24 },
  toggleItem: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  toggleLabel: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.muted },

  addBtn: { backgroundColor: C.blue, borderRadius: 10, paddingHorizontal: 16, paddingVertical: 8 },
  addBtnText: { fontFamily: 'Inter_600SemiBold', fontSize: 14, color: C.white },

  emptyWrap: { padding: 32, alignItems: 'center' },
  emptyTitle: { fontFamily: 'Inter_600SemiBold', fontSize: 18, color: C.navy, marginBottom: 8 },
  emptyText: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.muted, textAlign: 'center', lineHeight: 21, marginBottom: 20 },
  emptyBtn: { backgroundColor: C.blue, borderRadius: 12, paddingHorizontal: 24, paddingVertical: 14 },
  emptyBtnText: { fontFamily: 'Inter_600SemiBold', fontSize: 16, color: C.white },
});
