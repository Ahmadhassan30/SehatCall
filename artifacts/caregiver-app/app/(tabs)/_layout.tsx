import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';
import React from 'react';
import { useLanguage } from '@/context/LanguageContext';
import { ui } from '@/lib/ui';

export default function TabLayout() {
  const { t, isUrdu } = useLanguage();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: ui.surface,
          borderTopColor: ui.line,
          borderTopWidth: 1,
          height: 70,
          paddingBottom: 9,
          paddingTop: 8,
        },
        tabBarActiveTintColor: ui.primary,
        tabBarInactiveTintColor: ui.muted,
        tabBarLabelStyle: {
          fontFamily: isUrdu ? undefined : 'Inter_600SemiBold',
          fontSize: 12,
          marginTop: 1,
          letterSpacing: 0,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t('tabs.home'),
          tabBarIcon: ({ color, size }) => <Ionicons name="home-outline" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="medications"
        options={{
          title: t('tabs.medications'),
          tabBarIcon: ({ color, size }) => <Ionicons name="medical-outline" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="calls"
        options={{
          title: t('tabs.calls'),
          tabBarIcon: ({ color, size }) => <Ionicons name="call-outline" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: t('tabs.settings'),
          tabBarIcon: ({ color, size }) => <Ionicons name="settings-outline" color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
