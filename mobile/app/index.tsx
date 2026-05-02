/**
 * Splash placeholder shown while `useAuth.hydrate()` runs. After hydration
 * the root <Redirect> in `_layout.tsx` decides which route owns the user.
 */

import { ActivityIndicator } from 'react-native';

import { Screen } from '../src/components/Screen';
import { Wordmark } from '../src/components/Wordmark';
import { useTheme } from '../src/theme/ThemeProvider';

export default function Splash() {
  const theme = useTheme();
  return (
    <Screen scroll={false} contentStyle={{ alignItems: 'center', justifyContent: 'center', flex: 1 }}>
      <Wordmark size={36} />
      <ActivityIndicator color={theme.colors.accent2} style={{ marginTop: 18 }} />
    </Screen>
  );
}
