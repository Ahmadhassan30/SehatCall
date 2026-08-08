/**
 * DAWA Caregiver — main screen.
 *
 * Sections:
 *   • Header: patient name (Urdu) + settings gear icon
 *   • Call button (large, centered)
 *   • Live status steps (visible while a call is active)
 *   • Recent call history (FlatList)
 *   • Settings modal (API URL + admin token + medication)
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Animated,
  FlatList,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useColors } from '@/hooks/useColors';
import { CallLogEntry, CallPhase, useCall } from '@/context/CallContext';

// ─── Status step config ────────────────────────────────────────────────────────

const STATUS_STEPS: { phase: CallPhase; label: string }[] = [
  { phase: 'dispatched', label: 'Sent' },
  { phase: 'dialing', label: 'Dialing' },
  { phase: 'ringing', label: 'Ringing' },
  { phase: 'answered', label: 'Answered' },
  { phase: 'completed', label: 'Done' },
];

const PHASE_ORDER: CallPhase[] = [
  'idle',
  'dispatching',
  'dispatched',
  'dialing',
  'ringing',
  'answered',
  'completed',
  'failed',
];

function phaseIndex(p: CallPhase) {
  return PHASE_ORDER.indexOf(p);
}

function statusColor(status: string, colors: ReturnType<typeof useColors>): string {
  const s = status.toLowerCase();
  if (s === 'completed') return colors.success;
  if (s === 'failed') return colors.destructive;
  if (s === 'answered') return colors.primary;
  return colors.mutedForeground;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

// ─── Pulse animation for active call ──────────────────────────────────────────

function PulseRing({ color }: { color: string }) {
  const scale = useRef(new Animated.Value(1)).current;
  const opacity = useRef(new Animated.Value(0.6)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.parallel([
        Animated.sequence([
          Animated.timing(scale, { toValue: 1.6, duration: 900, useNativeDriver: true }),
          Animated.timing(scale, { toValue: 1, duration: 900, useNativeDriver: true }),
        ]),
        Animated.sequence([
          Animated.timing(opacity, { toValue: 0, duration: 900, useNativeDriver: true }),
          Animated.timing(opacity, { toValue: 0.6, duration: 900, useNativeDriver: true }),
        ]),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [scale, opacity]);

  return (
    <Animated.View
      style={[
        styles.pulseRing,
        { borderColor: color, transform: [{ scale }], opacity },
      ]}
    />
  );
}

// ─── History row ──────────────────────────────────────────────────────────────

function HistoryRow({ item }: { item: CallLogEntry }) {
  const colors = useColors();
  const sc = statusColor(item.status, colors);

  return (
    <View style={[styles.historyRow, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <View style={[styles.historyDot, { backgroundColor: sc }]} />
      <View style={styles.historyBody}>
        <Text style={[styles.historyMed, { color: colors.foreground }]} numberOfLines={1}>
          {item.medication}
        </Text>
        <Text style={[styles.historyStatus, { color: sc }]}>
          {item.status}
        </Text>
      </View>
      <View style={styles.historyTime}>
        <Text style={[styles.historyTimeDate, { color: colors.mutedForeground }]}>
          {formatDate(item.dispatchedAt)}
        </Text>
        <Text style={[styles.historyTimeClock, { color: colors.mutedForeground }]}>
          {formatTime(item.dispatchedAt)}
        </Text>
      </View>
    </View>
  );
}

// ─── Settings modal ───────────────────────────────────────────────────────────

interface SettingsModalProps {
  visible: boolean;
  onClose: () => void;
}

function SettingsModal({ visible, onClose }: SettingsModalProps) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { apiBaseUrl, adminToken, medicationName, setConfig } = useCall();

  const [urlDraft, setUrlDraft] = useState(apiBaseUrl);
  const [tokenDraft, setTokenDraft] = useState(adminToken);
  const [medDraft, setMedDraft] = useState(medicationName);
  const [saving, setSaving] = useState(false);

  // Sync drafts when modal opens
  useEffect(() => {
    if (visible) {
      setUrlDraft(apiBaseUrl);
      setTokenDraft(adminToken);
      setMedDraft(medicationName);
    }
  }, [visible, apiBaseUrl, adminToken, medicationName]);

  const save = async () => {
    const trimmedUrl = urlDraft.trim().replace(/\/$/, '');
    if (!trimmedUrl) {
      Alert.alert('API URL required', 'Enter the full URL to your DAWA backend, e.g. https://your-repl.replit.dev');
      return;
    }
    setSaving(true);
    await setConfig({
      apiBaseUrl: trimmedUrl,
      adminToken: tokenDraft.trim(),
      medicationName: medDraft.trim() || 'میٹفارمن',
    });
    setSaving(false);
    onClose();
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={[styles.modalContainer, { backgroundColor: colors.background }]}>
        {/* Handle */}
        <View style={[styles.modalHandle, { backgroundColor: colors.border }]} />

        <ScrollView
          style={styles.modalScroll}
          contentContainerStyle={[
            styles.modalContent,
            { paddingBottom: insets.bottom + 24 },
          ]}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={[styles.modalTitle, { color: colors.foreground }]}>
            Settings
          </Text>
          <Text style={[styles.modalSubtitle, { color: colors.mutedForeground }]}>
            Configure your DAWA backend connection
          </Text>

          <View style={styles.fieldGroup}>
            <Text style={[styles.fieldLabel, { color: colors.foreground }]}>
              Backend URL
            </Text>
            <TextInput
              value={urlDraft}
              onChangeText={setUrlDraft}
              placeholder="https://your-backend.replit.dev"
              placeholderTextColor={colors.mutedForeground}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              style={[
                styles.input,
                {
                  backgroundColor: colors.card,
                  borderColor: colors.border,
                  color: colors.foreground,
                },
              ]}
            />
            <Text style={[styles.fieldHint, { color: colors.mutedForeground }]}>
              No trailing slash. E.g. https://my-repl.replit.dev
            </Text>
          </View>

          <View style={styles.fieldGroup}>
            <Text style={[styles.fieldLabel, { color: colors.foreground }]}>
              Admin Token
            </Text>
            <TextInput
              value={tokenDraft}
              onChangeText={setTokenDraft}
              placeholder="DAWA_ADMIN_TOKEN value"
              placeholderTextColor={colors.mutedForeground}
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry
              style={[
                styles.input,
                {
                  backgroundColor: colors.card,
                  borderColor: colors.border,
                  color: colors.foreground,
                },
              ]}
            />
            <Text style={[styles.fieldHint, { color: colors.mutedForeground }]}>
              Matches DAWA_ADMIN_TOKEN in Replit Secrets
            </Text>
          </View>

          <View style={styles.fieldGroup}>
            <Text style={[styles.fieldLabel, { color: colors.foreground }]}>
              Medication Name (Urdu)
            </Text>
            <TextInput
              value={medDraft}
              onChangeText={setMedDraft}
              placeholder="میٹفارمن"
              placeholderTextColor={colors.mutedForeground}
              style={[
                styles.input,
                {
                  backgroundColor: colors.card,
                  borderColor: colors.border,
                  color: colors.foreground,
                },
              ]}
            />
          </View>

          <TouchableOpacity
            style={[styles.saveButton, { backgroundColor: colors.primary }]}
            onPress={save}
            activeOpacity={0.8}
            disabled={saving}
          >
            {saving ? (
              <ActivityIndicator color={colors.primaryForeground} />
            ) : (
              <Text style={[styles.saveButtonText, { color: colors.primaryForeground }]}>
                Save
              </Text>
            )}
          </TouchableOpacity>

          <TouchableOpacity onPress={onClose} style={styles.cancelButton}>
            <Text style={[styles.cancelText, { color: colors.mutedForeground }]}>Cancel</Text>
          </TouchableOpacity>
        </ScrollView>
      </View>
    </Modal>
  );
}

// ─── Main screen ──────────────────────────────────────────────────────────────

export default function HomeScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const {
    callPhase,
    failureReason,
    dispatchCall,
    dispatchError,
    callHistory,
    isLoadingHistory,
    refreshHistory,
    isConfigured,
    medicationName,
  } = useCall();

  const [settingsVisible, setSettingsVisible] = useState(false);

  // Load history on mount and when settings close
  const handleSettingsClose = useCallback(() => {
    setSettingsVisible(false);
    refreshHistory();
  }, [refreshHistory]);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  const isActive = callPhase !== 'idle';
  const isTerminal = callPhase === 'completed' || callPhase === 'failed';
  const canCall = isConfigured && callPhase === 'idle';

  // Compute button background outside JSX to avoid TS narrowing conflicts
  const buttonBg =
    callPhase === 'failed'
      ? colors.destructive
      : callPhase === 'completed'
      ? colors.success
      : isActive
      ? colors.primary
      : canCall
      ? colors.primary
      : colors.muted;

  const handleCallPress = async () => {
    if (!isConfigured) {
      setSettingsVisible(true);
      return;
    }
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    dispatchCall();
  };

  // Status step progress
  const currentStepIndex = STATUS_STEPS.findIndex((s) =>
    phaseIndex(s.phase) >= phaseIndex(callPhase),
  );
  const completedPhaseIdx = phaseIndex(callPhase);

  // Web top inset
  const webTopPad = Platform.OS === 'web' ? 67 : 0;
  const webBottomPad = Platform.OS === 'web' ? 34 : 0;

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      {/* Header */}
      <View
        style={[
          styles.header,
          {
            paddingTop: insets.top + 12 + webTopPad,
            borderBottomColor: colors.border,
            backgroundColor: colors.background,
          },
        ]}
      >
        <View>
          <Text style={[styles.headerPatientUrdu, { color: colors.primary }]}>
            احمد علی
          </Text>
          <Text style={[styles.headerPatientLatin, { color: colors.mutedForeground }]}>
            Ahmad Ali · Patient
          </Text>
        </View>
        <TouchableOpacity
          onPress={() => setSettingsVisible(true)}
          style={styles.settingsBtn}
          testID="settings-button"
        >
          <Feather name="settings" size={22} color={colors.mutedForeground} />
        </TouchableOpacity>
      </View>

      <FlatList
        data={callHistory}
        keyExtractor={(item) => item.logId}
        scrollEnabled={callHistory.length > 0}
        onRefresh={refreshHistory}
        refreshing={isLoadingHistory}
        contentContainerStyle={[
          styles.listContent,
          { paddingBottom: insets.bottom + webBottomPad + 24 },
        ]}
        ListHeaderComponent={
          <View>
            {/* Config banner */}
            {!isConfigured && (
              <Pressable
                onPress={() => setSettingsVisible(true)}
                style={[styles.banner, { backgroundColor: colors.secondary }]}
              >
                <Feather name="alert-circle" size={16} color={colors.primary} />
                <Text style={[styles.bannerText, { color: colors.secondaryForeground }]}>
                  Tap here to set up your DAWA backend URL and admin token
                </Text>
                <Feather name="chevron-right" size={16} color={colors.primary} />
              </Pressable>
            )}

            {/* Medication label */}
            <View style={[styles.medCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
              <Feather name="activity" size={14} color={colors.primary} />
              <Text style={[styles.medText, { color: colors.foreground }]}>
                {medicationName}
              </Text>
            </View>

            {/* Call button area */}
            <View style={styles.callArea}>
              {isActive && (
                <PulseRing
                  color={
                    callPhase === 'failed'
                      ? colors.destructive
                      : callPhase === 'completed'
                      ? colors.success
                      : colors.primary
                  }
                />
              )}
              <TouchableOpacity
                testID="call-button"
                style={[
                  styles.callButton,
                  { backgroundColor: buttonBg },
                ]}
                onPress={handleCallPress}
                activeOpacity={canCall ? 0.8 : 1}
                disabled={isActive && !isTerminal}
              >
                {callPhase === 'dispatching' ? (
                  <ActivityIndicator size="large" color="#fff" />
                ) : callPhase === 'completed' ? (
                  <Feather name="check" size={36} color="#fff" />
                ) : callPhase === 'failed' ? (
                  <Feather name="x" size={36} color="#fff" />
                ) : (
                  <Feather name="phone" size={36} color={canCall ? '#fff' : colors.mutedForeground} />
                )}
              </TouchableOpacity>

              <Text
                style={[
                  styles.callLabel,
                  {
                    color:
                      callPhase === 'failed'
                        ? colors.destructive
                        : callPhase === 'completed'
                        ? colors.success
                        : canCall
                        ? colors.foreground
                        : colors.mutedForeground,
                  },
                ]}
              >
                {callPhase === 'idle'
                  ? isConfigured
                    ? 'Call Patient'
                    : 'Setup required'
                  : callPhase === 'dispatching'
                  ? 'Sending…'
                  : callPhase === 'dispatched'
                  ? 'Call sent'
                  : callPhase === 'dialing'
                  ? 'Dialing…'
                  : callPhase === 'ringing'
                  ? 'Ringing…'
                  : callPhase === 'answered'
                  ? 'In conversation'
                  : callPhase === 'completed'
                  ? 'Call complete'
                  : 'Call failed'}
              </Text>

              {/* Error */}
              {dispatchError && (
                <Text style={[styles.errorText, { color: colors.destructive }]}>
                  {dispatchError}
                </Text>
              )}
              {failureReason && (
                <Text style={[styles.errorText, { color: colors.destructive }]}>
                  {failureReason}
                </Text>
              )}
            </View>

            {/* Status steps */}
            {isActive && (
              <View style={[styles.stepsCard, { backgroundColor: colors.card, borderColor: colors.border }]}>
                {callPhase === 'failed' ? (
                  <View style={styles.failedRow}>
                    <Feather name="x-circle" size={16} color={colors.destructive} />
                    <Text style={[styles.failedText, { color: colors.destructive }]}>
                      Call failed
                      {failureReason ? ` — ${failureReason}` : ''}
                    </Text>
                  </View>
                ) : (
                  STATUS_STEPS.map((step, idx) => {
                    const done = phaseIndex(step.phase) < completedPhaseIdx;
                    const active = step.phase === callPhase;
                    return (
                      <View key={step.phase} style={styles.stepRow}>
                        <View
                          style={[
                            styles.stepDot,
                            {
                              backgroundColor: done || active ? colors.primary : colors.border,
                              borderColor: active ? colors.primary : 'transparent',
                            },
                          ]}
                        >
                          {done && (
                            <Feather name="check" size={10} color="#fff" />
                          )}
                        </View>
                        {idx < STATUS_STEPS.length - 1 && (
                          <View
                            style={[
                              styles.stepLine,
                              { backgroundColor: done ? colors.primary : colors.border },
                            ]}
                          />
                        )}
                        <Text
                          style={[
                            styles.stepLabel,
                            {
                              color: done || active ? colors.foreground : colors.mutedForeground,
                              fontFamily: active ? 'Inter_600SemiBold' : 'Inter_400Regular',
                            },
                          ]}
                        >
                          {step.label}
                        </Text>
                        {active && (
                          <ActivityIndicator
                            size="small"
                            color={colors.primary}
                            style={styles.stepSpinner}
                          />
                        )}
                      </View>
                    );
                  })
                )}
              </View>
            )}

            {/* History header */}
            <View style={styles.sectionHeader}>
              <Text style={[styles.sectionTitle, { color: colors.foreground }]}>
                Recent Calls
              </Text>
              {isLoadingHistory && (
                <ActivityIndicator size="small" color={colors.primary} />
              )}
            </View>
          </View>
        }
        ListEmptyComponent={
          !isLoadingHistory ? (
            <View style={styles.emptyState}>
              <Feather name="phone-missed" size={32} color={colors.mutedForeground} />
              <Text style={[styles.emptyText, { color: colors.mutedForeground }]}>
                No calls yet
              </Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => <HistoryRow item={item} />}
        ItemSeparatorComponent={() => <View style={{ height: 8 }} />}
      />

      <SettingsModal
        visible={settingsVisible}
        onClose={handleSettingsClose}
      />
    </View>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  screen: { flex: 1 },

  // Header
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingBottom: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  headerPatientUrdu: {
    fontSize: 26,
    fontFamily: 'Inter_700Bold',
  },
  headerPatientLatin: {
    fontSize: 13,
    fontFamily: 'Inter_400Regular',
    marginTop: 2,
  },
  settingsBtn: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },

  // List
  listContent: { paddingHorizontal: 20, paddingTop: 16 },

  // Banner
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 10,
    padding: 12,
    marginBottom: 14,
  },
  bannerText: { flex: 1, fontSize: 13, fontFamily: 'Inter_500Medium' },

  // Med card
  medCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 28,
    alignSelf: 'flex-start',
  },
  medText: { fontSize: 15, fontFamily: 'Inter_600SemiBold' },

  // Call button
  callArea: {
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 32,
  },
  callButton: {
    width: 104,
    height: 104,
    borderRadius: 52,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.18,
    shadowRadius: 12,
    elevation: 6,
  },
  callLabel: {
    marginTop: 14,
    fontSize: 16,
    fontFamily: 'Inter_600SemiBold',
  },
  errorText: {
    marginTop: 8,
    fontSize: 13,
    fontFamily: 'Inter_400Regular',
    textAlign: 'center',
    maxWidth: 280,
  },

  // Pulse ring
  pulseRing: {
    position: 'absolute',
    width: 104,
    height: 104,
    borderRadius: 52,
    borderWidth: 3,
  },

  // Steps card
  stepsCard: {
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 16,
    marginBottom: 28,
    gap: 4,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 32,
  },
  stepDot: {
    width: 20,
    height: 20,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
  },
  stepLine: {
    position: 'absolute',
    left: 9,
    top: 22,
    width: 2,
    height: 12,
    borderRadius: 1,
  },
  stepLabel: { fontSize: 14 },
  stepSpinner: { marginLeft: 4 },

  failedRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  failedText: { fontSize: 14, fontFamily: 'Inter_500Medium' },

  // Section header
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  sectionTitle: { fontSize: 16, fontFamily: 'Inter_600SemiBold' },

  // History row
  historyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    paddingVertical: 12,
    paddingHorizontal: 14,
    gap: 12,
  },
  historyDot: { width: 10, height: 10, borderRadius: 5 },
  historyBody: { flex: 1 },
  historyMed: { fontSize: 15, fontFamily: 'Inter_600SemiBold' },
  historyStatus: { fontSize: 12, fontFamily: 'Inter_500Medium', marginTop: 2, textTransform: 'capitalize' },
  historyTime: { alignItems: 'flex-end' },
  historyTimeDate: { fontSize: 12, fontFamily: 'Inter_400Regular' },
  historyTimeClock: { fontSize: 12, fontFamily: 'Inter_400Regular', marginTop: 2 },

  // Empty state
  emptyState: { alignItems: 'center', gap: 10, marginTop: 32 },
  emptyText: { fontSize: 14, fontFamily: 'Inter_400Regular' },

  // Settings modal
  modalContainer: { flex: 1 },
  modalHandle: { width: 40, height: 4, borderRadius: 2, alignSelf: 'center', marginTop: 12 },
  modalScroll: { flex: 1 },
  modalContent: { padding: 24 },
  modalTitle: { fontSize: 22, fontFamily: 'Inter_700Bold', marginBottom: 4 },
  modalSubtitle: { fontSize: 14, fontFamily: 'Inter_400Regular', marginBottom: 28 },
  fieldGroup: { marginBottom: 20 },
  fieldLabel: { fontSize: 14, fontFamily: 'Inter_600SemiBold', marginBottom: 8 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    fontFamily: 'Inter_400Regular',
  },
  fieldHint: { fontSize: 12, fontFamily: 'Inter_400Regular', marginTop: 6 },
  saveButton: {
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  saveButtonText: { fontSize: 16, fontFamily: 'Inter_600SemiBold' },
  cancelButton: { alignItems: 'center', marginTop: 14, paddingVertical: 8 },
  cancelText: { fontSize: 15, fontFamily: 'Inter_400Regular' },
});
