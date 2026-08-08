/**
 * Semantic design tokens — DAWA Caregiver app.
 * Medical / care aesthetic: sky-blue primary, clean light surfaces.
 */

const colors = {
  light: {
    // Legacy aliases
    text: '#0F172A',
    tint: '#0EA5E9',

    // Core surfaces
    background: '#F0F6FB',
    foreground: '#0F172A',

    // Cards / elevated surfaces
    card: '#FFFFFF',
    cardForeground: '#0F172A',

    // Primary — sky blue (trust, medical)
    primary: '#0EA5E9',
    primaryForeground: '#FFFFFF',

    // Secondary — pale blue tint
    secondary: '#E0F2FE',
    secondaryForeground: '#0369A1',

    // Muted / subdued
    muted: '#F1F5F9',
    mutedForeground: '#64748B',

    // Accent (same as primary for this app)
    accent: '#0EA5E9',
    accentForeground: '#FFFFFF',

    // Status colors
    success: '#10B981',
    successForeground: '#FFFFFF',
    warning: '#F59E0B',
    warningForeground: '#FFFFFF',

    // Destructive
    destructive: '#EF4444',
    destructiveForeground: '#FFFFFF',

    // Borders / inputs
    border: '#E2E8F0',
    input: '#E2E8F0',
  },

  dark: {
    text: '#F8FAFC',
    tint: '#38BDF8',

    background: '#0F172A',
    foreground: '#F8FAFC',

    card: '#1E293B',
    cardForeground: '#F8FAFC',

    primary: '#38BDF8',
    primaryForeground: '#0F172A',

    secondary: '#1E3A5F',
    secondaryForeground: '#7DD3FC',

    muted: '#1E293B',
    mutedForeground: '#94A3B8',

    accent: '#38BDF8',
    accentForeground: '#0F172A',

    success: '#34D399',
    successForeground: '#0F172A',
    warning: '#FBBF24',
    warningForeground: '#0F172A',

    destructive: '#F87171',
    destructiveForeground: '#0F172A',

    border: '#334155',
    input: '#334155',
  },

  radius: 12,
};

export default colors;
