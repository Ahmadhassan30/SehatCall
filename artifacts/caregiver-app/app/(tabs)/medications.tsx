import React, { useCallback } from 'react';
import { Alert, FlatList, RefreshControl, StyleSheet, Switch, Text, TouchableOpacity, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { DawaHeader } from '@/components/DawaHeader';
import { useLanguage } from '@/context/LanguageContext';
import { useP3, type P3Medication } from '@/context/P3Context';
import { radius, ui } from '@/lib/ui';

function MedicineCard({
  med,
  onEdit,
  onToggleActive,
  onToggleAutomaticCalls,
}: {
  med: P3Medication;
  onEdit: () => void;
  onToggleActive: (value: boolean) => void;
  onToggleAutomaticCalls: (value: boolean) => void;
}) {
  const { isUrdu, t } = useLanguage();
  const rtl = isUrdu ? styles.rtlText : undefined;
  const cues: Record<string, string> = {
    package_color: t('meds.package'),
    stripe_color: t('meds.stripe'),
    tablet_shape: t('meds.shape'),
    storage_location: t('meds.stored'),
  };

  return (
    <TouchableOpacity
      style={[styles.card, !med.active && styles.cardInactive]}
      onPress={onEdit}
      activeOpacity={0.75}
      accessibilityRole="button"
    >
      <View style={[styles.cardHeader, isUrdu && styles.rowRtl]}>
        <View style={styles.titleWrap}>
          <Text style={[styles.cardTitle, !med.active && styles.mutedTitle, rtl]}>{med.nickname || med.clinicalName}</Text>
          {med.nickname ? <Text style={[styles.cardSub, rtl]}>{med.clinicalName}</Text> : null}
        </View>
        <Text style={styles.cardTime}>{med.scheduleTime}</Text>
      </View>

      <Text style={[styles.dose, rtl]}>{med.doseInstruction}  {med.dosage}</Text>

      {Object.entries(med.cues ?? {}).length ? (
        <View style={[styles.cueWrap, isUrdu && styles.rowRtl]}>
          {Object.entries(med.cues).map(([key, value]) => (
            <View key={key} style={[styles.cue, isUrdu && styles.rowRtl]}>
              <Text style={[styles.cueLabel, rtl]}>{cues[key] ?? key}</Text>
              <Text style={[styles.cueValue, rtl]}>{value}</Text>
            </View>
          ))}
        </View>
      ) : null}

      {med.warnings?.map((warning, index) => (
        <View key={`${med.id}-warning-${index}`} style={styles.warning}>
          <Text style={[styles.warningText, rtl]}>{warning}</Text>
        </View>
      ))}

      {med.doctorInstructions ? (
        <View style={styles.note}>
          <Text style={[styles.noteLabel, rtl]}>
            {t('meds.doctor')}{med.doctorName ? `  ${med.doctorName}` : ''}
          </Text>
          <Text style={[styles.noteText, rtl]}>{med.doctorInstructions}</Text>
        </View>
      ) : null}

      <View style={[styles.toggleRow, isUrdu && styles.rowRtl]}>
        <View style={[styles.toggleItem, isUrdu && styles.rowRtl]}>
          <Text style={[styles.toggleLabel, rtl]}>{t('common.active')}</Text>
          <Switch
            value={med.active}
            onValueChange={onToggleActive}
            trackColor={{ true: ui.primary, false: ui.line }}
            thumbColor={ui.surface}
          />
        </View>
        <View style={[styles.toggleItem, isUrdu && styles.rowRtl]}>
          <Text style={[styles.toggleLabel, rtl]}>{t('meds.automaticCalls')}</Text>
          <Switch
            value={med.autoCallEnabled}
            onValueChange={onToggleAutomaticCalls}
            disabled={!med.active}
            trackColor={{ true: ui.primary, false: ui.line }}
            thumbColor={ui.surface}
          />
        </View>
      </View>
    </TouchableOpacity>
  );
}

export default function MedicationsScreen() {
  const { medications, medicationsLoading, refreshMedications, updateMedication } = useP3();
  const { isUrdu, t } = useLanguage();
  const router = useRouter();
  const rtl = isUrdu ? styles.rtlText : undefined;
  const active = medications.filter((med) => med.active);
  const inactive = medications.filter((med) => !med.active);
  type Row = { type: 'header'; key: string; label: string } | { type: 'medicine'; key: string; medicine: P3Medication };
  const rows: Row[] = [];

  if (active.length) {
    rows.push({ type: 'header', key: 'active', label: t('common.active') });
    active.forEach((medicine) => rows.push({ type: 'medicine', key: medicine.id, medicine }));
  }
  if (inactive.length) {
    rows.push({ type: 'header', key: 'inactive', label: t('common.inactive') });
    inactive.forEach((medicine) => rows.push({ type: 'medicine', key: medicine.id, medicine }));
  }

  const onRefresh = useCallback(() => refreshMedications(), [refreshMedications]);
  const toggle = useCallback(async (medicine: P3Medication, patch: { active?: boolean; autoCallEnabled?: boolean }) => {
    try {
      await updateMedication(medicine.id, patch);
    } catch {
      Alert.alert(t('common.updateFailed'), t('common.tryAgain'));
    }
  }, [t, updateMedication]);

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <DawaHeader
        title={t('meds.title')}
        right={
          <TouchableOpacity
            style={styles.addButton}
            onPress={() => router.push('/medication/new')}
            accessibilityLabel={t('meds.add')}
            accessibilityRole="button"
          >
            <Ionicons name="add" size={22} color={ui.surface} />
          </TouchableOpacity>
        }
      />
      <FlatList
        data={rows}
        keyExtractor={(item) => item.key}
        renderItem={({ item }) => item.type === 'header' ? (
          <Text style={[styles.groupLabel, rtl]}>{item.label}</Text>
        ) : (
          <MedicineCard
            med={item.medicine}
            onEdit={() => router.push(`/medication/${item.medicine.id}`)}
            onToggleActive={(value) => toggle(item.medicine, { active: value })}
            onToggleAutomaticCalls={(value) => toggle(item.medicine, { autoCallEnabled: value })}
          />
        )}
        contentContainerStyle={[styles.list, medications.length === 0 && styles.emptyList]}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        refreshControl={<RefreshControl refreshing={medicationsLoading} onRefresh={onRefresh} tintColor={ui.primary} />}
        ListEmptyComponent={!medicationsLoading ? (
          <View style={styles.emptyWrap}>
            <Ionicons name="medical-outline" size={28} color={ui.muted} />
            <Text style={[styles.emptyTitle, rtl]}>{t('meds.empty')}</Text>
            <Text style={[styles.emptyText, rtl]}>{t('meds.emptyBody')}</Text>
            <TouchableOpacity style={styles.emptyButton} onPress={() => router.push('/medication/new')}>
              <Text style={[styles.emptyButtonText, rtl]}>{t('meds.addFirst')}</Text>
            </TouchableOpacity>
          </View>
        ) : null}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: ui.canvas },
  list: { padding: 16, paddingBottom: 40 },
  emptyList: { flexGrow: 1, justifyContent: 'center' },
  separator: { height: 10 },
  groupLabel: { fontFamily: 'Inter_700Bold', fontSize: 15, color: ui.text, marginTop: 14, marginBottom: 4, paddingHorizontal: 2 },
  card: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, padding: 18 },
  cardInactive: { backgroundColor: ui.surfaceMuted, opacity: 0.78 },
  cardHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  rowRtl: { flexDirection: 'row-reverse' },
  titleWrap: { flex: 1 },
  cardTitle: { fontFamily: 'Inter_700Bold', fontSize: 21, lineHeight: 27, color: ui.text },
  mutedTitle: { color: ui.muted },
  cardSub: { fontFamily: 'Inter_500Medium', fontSize: 14, color: ui.muted, marginTop: 3 },
  cardTime: { fontFamily: 'Inter_700Bold', fontSize: 18, color: ui.primary },
  dose: { fontFamily: 'Inter_500Medium', fontSize: 15, lineHeight: 21, color: ui.muted, marginTop: 10 },
  cueWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 12 },
  cue: { flexDirection: 'row', gap: 5, backgroundColor: ui.surfaceMuted, borderRadius: radius.small, paddingHorizontal: 9, paddingVertical: 5 },
  cueLabel: { fontFamily: 'Inter_400Regular', fontSize: 12, color: ui.muted },
  cueValue: { fontFamily: 'Inter_600SemiBold', fontSize: 12, color: ui.text },
  warning: { backgroundColor: ui.warningSoft, borderLeftWidth: 3, borderLeftColor: ui.warning, borderRadius: radius.small, padding: 10, marginTop: 10 },
  warningText: { fontFamily: 'Inter_400Regular', fontSize: 13, lineHeight: 18, color: ui.warning },
  note: { backgroundColor: ui.surfaceMuted, borderRadius: radius.small, padding: 10, marginTop: 10 },
  noteLabel: { fontFamily: 'Inter_600SemiBold', fontSize: 12, color: ui.muted },
  noteText: { fontFamily: 'Inter_400Regular', fontSize: 13, lineHeight: 18, color: ui.text, marginTop: 3 },
  toggleRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 20, borderTopWidth: 1, borderTopColor: ui.line, paddingTop: 12, marginTop: 14 },
  toggleItem: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  toggleLabel: { fontFamily: 'Inter_600SemiBold', fontSize: 14, color: ui.text },
  addButton: { width: 38, height: 38, borderRadius: radius.medium, backgroundColor: ui.primary, alignItems: 'center', justifyContent: 'center' },
  emptyWrap: { alignItems: 'center', paddingHorizontal: 28 },
  emptyTitle: { fontFamily: 'Inter_700Bold', fontSize: 21, color: ui.text, marginTop: 12 },
  emptyText: { fontFamily: 'Inter_400Regular', fontSize: 15, lineHeight: 23, color: ui.muted, textAlign: 'center', marginTop: 7, maxWidth: 320 },
  emptyButton: { backgroundColor: ui.primary, borderRadius: radius.medium, paddingHorizontal: 18, paddingVertical: 12, marginTop: 18 },
  emptyButtonText: { fontFamily: 'Inter_700Bold', fontSize: 15, color: ui.surface },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});
