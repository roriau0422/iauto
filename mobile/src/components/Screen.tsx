/**
 * Screen frame — vertical gradient background + subtle grid texture +
 * safe-area aware padding. Every route renders inside this so the
 * immersive blue shows through behind every surface.
 */

import { LinearGradient } from 'expo-linear-gradient';
import { type ReactNode } from 'react';
import { ScrollView, StatusBar, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '../theme/ThemeProvider';
import { accentOverlay, backgroundGradient } from '../theme/tokens';
import { useTweaks } from '../theme/ThemeProvider';

type Props = {
  children: ReactNode;
  scroll?: boolean;
  style?: StyleProp<ViewStyle>;
  contentStyle?: StyleProp<ViewStyle>;
  /** When false the screen does not extend under the bottom safe area. */
  edges?: ('top' | 'bottom' | 'left' | 'right')[];
};

export function Screen({ children, scroll = true, style, contentStyle, edges = ['top'] }: Props) {
  const theme = useTheme();
  const { tweaks } = useTweaks();
  const insets = useSafeAreaInsets();
  const Container = scroll ? ScrollView : View;

  return (
    <View style={[styles.fill, { backgroundColor: theme.colors.bg0 }]}>
      <StatusBar barStyle={theme.name === 'dark' ? 'light-content' : 'dark-content'} />
      <LinearGradient
        colors={backgroundGradient(theme.name) as [string, string, string]}
        style={StyleSheet.absoluteFill}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
      />
      <LinearGradient
        colors={accentOverlay(theme.name, tweaks.accent) as [string, string]}
        style={[StyleSheet.absoluteFill, { height: 360 }]}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
      />
      <SafeAreaView edges={edges} style={[styles.fill, style]}>
        <Container
          style={styles.fill}
          contentContainerStyle={[
            scroll
              ? { paddingTop: theme.spacing.md, paddingBottom: insets.bottom + 80 }
              : undefined,
            contentStyle,
          ]}
          showsVerticalScrollIndicator={false}
        >
          {children}
        </Container>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
