/**
 * Business tab tree — Хяналт / Агуулах / Зар / Сошиал / Чат.
 */

import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';
import { Platform, StyleSheet } from 'react-native';

import { useTheme } from '../../src/theme/ThemeProvider';

export default function BusinessLayout() {
  const theme = useTheme();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarShowLabel: true,
        tabBarActiveTintColor: theme.colors.accent2,
        tabBarInactiveTintColor: theme.colors.text3,
        tabBarStyle: [
          styles.bar,
          {
            backgroundColor:
              theme.name === 'dark' ? 'rgba(10,16,36,0.9)' : 'rgba(255,255,255,0.95)',
            borderTopColor: theme.colors.stroke2,
          },
        ],
        tabBarLabelStyle: styles.label,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'ХЯНАЛТ',
          tabBarIcon: ({ color }) => <Feather name="home" size={20} color={color} />,
        }}
      />
      <Tabs.Screen
        name="warehouse"
        options={{
          title: 'АГУУЛАХ',
          tabBarIcon: ({ color }) => <Feather name="package" size={20} color={color} />,
        }}
      />
      <Tabs.Screen
        name="market"
        options={{
          title: 'ЗАХ',
          tabBarIcon: ({ color }) => <Feather name="search" size={20} color={color} />,
        }}
      />
      <Tabs.Screen
        name="stories"
        options={{
          title: 'СОШИАЛ',
          tabBarIcon: ({ color }) => (
            <MaterialCommunityIcons name="circle-multiple-outline" size={22} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="chat"
        options={{
          title: 'ЧАТ',
          tabBarIcon: ({ color }) => <Feather name="message-square" size={20} color={color} />,
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  bar: {
    borderTopWidth: StyleSheet.hairlineWidth,
    height: Platform.OS === 'ios' ? 86 : 72,
    paddingTop: 6,
  },
  label: {
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.4,
    textTransform: 'uppercase',
  },
});
