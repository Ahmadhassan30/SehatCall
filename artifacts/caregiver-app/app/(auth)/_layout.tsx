import { Stack } from 'expo-router';

/** Auth-flow screens: sign-in + onboarding. No tab bar, no back button. */
export default function AuthLayout() {
  return (
    <Stack screenOptions={{ headerShown: false, animation: 'fade' }}>
      <Stack.Screen name="sign-in" />
      <Stack.Screen name="onboarding" />
    </Stack>
  );
}
