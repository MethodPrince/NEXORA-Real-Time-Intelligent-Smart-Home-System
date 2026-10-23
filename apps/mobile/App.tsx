import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Speech from "expo-speech";
import {
  ExpoSpeechRecognitionModule,
  useSpeechRecognitionEvent,
} from "expo-speech-recognition";
import { StatusBar } from "expo-status-bar";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  ApiError,
  type AutomationCreate,
  type AutomationRule,
  type AutomationUpdate,
  colors,
  createDemoDevices,
  isDeviceEvent,
  isAssistantGreeting,
  matchVoiceTargets,
  NexoraApi,
  parseVoiceCommand,
  tickSimulatedSensors,
  toggleSimulatedDevice,
  voiceDeviceKind,
  websocketUrl,
  type ActivityItem,
  type Device,
  type DeviceEvent,
  type SimulatedDevice,
} from "@nexora/shared";

type Section = "home" | "devices" | "activity" | "automations" | "nora" | "settings";
type AnyDevice = Device | SimulatedDevice;

const apiBase = process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000";
const api = new NexoraApi(apiBase);
const navigation: { id: Section; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: "home", label: "Home", icon: "home-outline" },
  { id: "devices", label: "Devices", icon: "hardware-chip-outline" },
  { id: "activity", label: "Activity", icon: "pulse-outline" },
  { id: "nora", label: "NORA", icon: "sparkles-outline" },
  { id: "settings", label: "Settings", icon: "settings-outline" },
];

function isSimulated(device: AnyDevice): device is SimulatedDevice {
  return "demo" in device && device.demo;
}

function onState(device: AnyDevice) {
  if (isSimulated(device)) return device.power;
  if (device.device_type.toLowerCase().includes("curtain")) {
    return device.state?.open ?? (device.state?.position ?? 0) > 0;
  }
  return device.state?.power
    ?? (device.status.toLowerCase() === "on" || device.status.toLowerCase() === "active");
}

function deviceStateLabel(device: AnyDevice) {
  if (!device.online) return "Offline";
  if (isSimulated(device)) return device.power ? "Powered on · local demo" : "Powered off · local demo";
  if (device.device_type.toLowerCase().includes("curtain")) {
    const position = device.state?.position;
    return position === undefined ? device.status : `${position}% open`;
  }
  if (device.device_type.toLowerCase().includes("fan") && device.state?.speed !== undefined) {
    return `${onState(device) ? "On" : "Off"} · speed ${device.state.speed}/3`;
  }
  if (device.device_type.toLowerCase().includes("light") && device.state?.brightness !== undefined) {
    return `${onState(device) ? "On" : "Off"} · brightness ${device.state.brightness}%`;
  }
  return onState(device) ? "Powered on" : "Powered off";
}

function controlLabel(device: AnyDevice) {
  if (device.device_type.toLowerCase().includes("curtain")) {
    return onState(device) ? "Close" : "Open";
  }
  return onState(device) ? "Turn off" : "Turn on";
}

function deviceIcon(type: string): keyof typeof Ionicons.glyphMap {
  if (/fan/i.test(type)) return "sync-outline";
  if (/sensor|temperature/i.test(type)) return "thermometer-outline";
  return "bulb-outline";
}

function App() {
  const [section, setSection] = useState<Section>("home");
  const [devices, setDevices] = useState<Device[]>([]);
  const [automations, setAutomations] = useState<AutomationRule[]>([]);
  const [automationName, setAutomationName] = useState("");
  const [automationTime, setAutomationTime] = useState("19:00");
  const [automationDeviceId, setAutomationDeviceId] = useState("");
  const [automationCommand, setAutomationCommand] =
    useState<AutomationCreate["action"]["command"]>("turn_on");
  const [automationLoading, setAutomationLoading] = useState(false);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [simDevices, setSimDevices] = useState<SimulatedDevice[]>(createDemoDevices);
  const [simulation, setSimulation] = useState(true);
  const [apiStatus, setApiStatus] = useState<"checking" | "connected" | "offline">("checking");
  const [socketStatus, setSocketStatus] = useState<"checking" | "connected" | "offline">("checking");
  const [events, setEvents] = useState<DeviceEvent[]>([]);
  const [notifications, setNotifications] = useState<ActivityItem[]>([]);
  const [addVisible, setAddVisible] = useState(false);
  const [name, setName] = useState("");
  const [room, setRoom] = useState("");
  const [deviceType, setDeviceType] = useState("smart_light");
  const [simulatedDevice, setSimulatedDevice] = useState(false);
  const [noraInput, setNoraInput] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("Tap the microphone, then say “Hey Method” or “Hello Method” and your command.");
  const [isListening, setIsListening] = useState(false);
  const [noraMessages, setNoraMessages] = useState([
    { from: "nora", text: "Hi, I’m NORA. You can call me Method. Tap the microphone and say “Hey Method, turn on the living room light.”" },
  ]);
  const [noticeVisible, setNoticeVisible] = useState(false);
  const [toast, setToast] = useState("");
  const [sensorTick, setSensorTick] = useState(0);
  const visibleDevices: AnyDevice[] = useMemo(
    () => [...devices, ...(simulation ? simDevices : [])],
    [devices, simDevices, simulation],
  );
  const automationDevices = devices.filter((device) =>
    /light|lamp|fan|curtain/i.test(device.device_type),
  );
  const selectedAutomationDevice = automationDevices.find(
    (device) => device.id === automationDeviceId,
  ) ?? automationDevices[0];

  useSpeechRecognitionEvent("start", () => setIsListening(true));
  useSpeechRecognitionEvent("end", () => setIsListening(false));
  useSpeechRecognitionEvent("result", (event) => {
    const transcript = event.results[0]?.transcript.trim();
    if (!transcript) return;
    setNoraInput(transcript);
    if (event.isFinal) {
      setVoiceStatus("Command received.");
      void sendNora(transcript);
    }
  });
  useSpeechRecognitionEvent("error", (event) => {
    setIsListening(false);
    const message = event.error === "not-allowed"
      ? "Microphone or speech permission was denied."
      : `Voice input failed: ${event.message}`;
    setVoiceStatus(message);
    setToast(message);
  });

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        await api.health();
        const nextDevices = await api.listDevices();
        if (active) {
          setDevices(nextDevices);
          setApiStatus("connected");
        }
      } catch {
        if (active) setApiStatus("offline");
      }
    };
    void refresh();
    const interval = setInterval(() => void refresh(), 30_000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (section !== "automations") return;
    let active = true;
    setAutomationLoading(true);
    void api.listAutomations().then((rules) => {
      if (active) {
        setAutomations(rules);
        setToast("");
      }
    }).catch((error: unknown) => {
      if (active) setToast(error instanceof ApiError ? error.message : "Could not load automations.");
    }).finally(() => {
      if (active) setAutomationLoading(false);
    });
    return () => {
      active = false;
    };
  }, [section]);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    const connect = () => {
      if (closed) return;
      try {
        socket = new WebSocket(websocketUrl(apiBase, apiBase));
        socket.onopen = () => setSocketStatus("connected");
        socket.onmessage = (message) => {
          try {
            const event: unknown = JSON.parse(String(message.data));
            if (isDeviceEvent(event)) receiveEvent(event);
          } catch {
            // The backend also echoes text frames; only structured events are consumed.
          }
        };
        socket.onerror = () => setSocketStatus("offline");
        socket.onclose = () => {
          setSocketStatus("offline");
          if (!closed) retry = setTimeout(connect, 2500);
        };
      } catch {
        setSocketStatus("offline");
        retry = setTimeout(connect, 2500);
      }
    };
    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, []);

  useEffect(() => {
    if (!simulation) return;
    const interval = setInterval(() => setSensorTick((tick) => tick + 1), 3500);
    return () => clearInterval(interval);
  }, [simulation]);

  useEffect(() => {
    if (!sensorTick || !simulation) return;
    const result = tickSimulatedSensors(simDevices, sensorTick);
    setSimDevices(result.devices);
    setEvents((current) => [...result.events, ...current].slice(0, 80));
  }, [sensorTick, simulation]);

  function notify(title: string, detail: string) {
    setNotifications((current) => [
      { id: `${Date.now()}`, title, detail, timestamp: new Date().toISOString(), kind: "device" as const },
      ...current,
    ].slice(0, 20));
  }

  function receiveEvent(event: DeviceEvent) {
    setEvents((current) => [event, ...current].slice(0, 80));
    if (event.device_id) {
      setDevices((current) => current.map((device) => {
        if (device.id !== event.device_id) return device;
        if (event.type === "device_state" && event.status) {
          return {
            ...device,
            status: event.status,
            state: event.state ?? device.state,
            online: event.online ?? device.online,
          };
        }
        if (event.type === "device_availability" && typeof event.online === "boolean") {
          return { ...device, online: event.online };
        }
        return device;
      }));
    }
    notify(event.type.replaceAll("_", " "), event.device_id ?? event.message ?? "Backend event");
  }

  async function control(device: AnyDevice) {
    if (isSimulated(device)) {
      const result = toggleSimulatedDevice(device);
      setSimDevices((current) => current.map((item) => item.id === device.id ? result.device : item));
      setEvents((current) => [result.event, ...current].slice(0, 80));
      notify(device.name, `Local simulation · ${result.device.power ? "on" : "off"}`);
      return;
    }
    try {
      const isCurtain = device.device_type.toLowerCase().includes("curtain");
      const result = await api.sendCommand(
        device.id,
        isCurtain
          ? { command: onState(device) ? "close" : "open" }
          : { command: "set_power", parameters: { enabled: !onState(device) } },
      );
      if (result.state) {
        setDevices((current) => current.map((item) => item.id === device.id
          ? {
            ...item,
            status: isCurtain
              ? (result.state?.position === 100 ? "Open" : result.state?.position === 0 ? "Closed" : "Partially open")
              : result.state?.power ? "On" : "Off",
            online: result.online ?? item.online,
            state: result.state,
          }
          : item));
      }
      setToast(result.status === "applied"
        ? `${device.name} state updated.`
        : "Command queued. Waiting for device state.");
    } catch (error) {
      setToast(error instanceof ApiError ? error.message : "Unable to send command.");
    }
  }

  async function addDevice() {
    if (!name.trim() || !deviceType.trim()) {
      Alert.alert("Missing details", "Enter a name and device type.");
      return;
    }
    try {
      const created = await api.createDevice({
        name: name.trim(),
        room: room.trim() || null,
        device_type: deviceType.trim(),
        simulated: simulatedDevice,
      });
      setDevices((current) => [...current, created]);
      setAddVisible(false);
      setName("");
      setRoom("");
      setSimulatedDevice(false);
      setToast("Device registered.");
    } catch (error) {
      setToast(error instanceof ApiError ? error.message : "Unable to create device.");
    }
  }

  async function createAutomation() {
    if (!automationName.trim() || !selectedAutomationDevice) {
      setToast("Enter a name and select a supported device.");
      return;
    }
    const isCurtain = selectedAutomationDevice.device_type.toLowerCase().includes("curtain");
    const command = isCurtain
      ? (automationCommand === "close" ? "close" : "open")
      : (automationCommand === "turn_off" ? "turn_off" : "turn_on");
    const automation: AutomationCreate = {
      name: automationName.trim(),
      trigger: {
        type: "schedule",
        time: automationTime,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        days: [0, 1, 2, 3, 4, 5, 6],
      },
      action: { device_id: selectedAutomationDevice.id, command },
    };
    setAutomationBusy(true);
    try {
      const created = await api.createAutomation(automation);
      setAutomations((current) => [created, ...current]);
      setAutomationName("");
      setToast("Automation saved to your account.");
    } catch (error) {
      setToast(error instanceof ApiError ? error.message : "Could not save automation.");
    } finally {
      setAutomationBusy(false);
    }
  }

  async function toggleAutomation(rule: AutomationRule) {
    await changeAutomation(rule, { enabled: !rule.enabled });
  }

  async function removeAutomation(rule: AutomationRule) {
    setAutomationBusy(true);
    try {
      await api.deleteAutomation(rule.id);
      setAutomations((current) => current.filter((item) => item.id !== rule.id));
      setToast("Automation deleted.");
    } catch (error) {
      setToast(error instanceof ApiError ? error.message : "Could not delete automation.");
    } finally {
      setAutomationBusy(false);
    }
  }

  async function changeAutomation(rule: AutomationRule, update: AutomationUpdate) {
    setAutomationBusy(true);
    try {
      const saved = await api.updateAutomation(rule.id, update);
      setAutomations((current) => current.map((item) => item.id === saved.id ? saved : item));
    } catch (error) {
      setToast(error instanceof ApiError ? error.message : "Could not update automation.");
    } finally {
      setAutomationBusy(false);
    }
  }

  function deleteDevice(device: AnyDevice) {
    if (isSimulated(device)) return;
    Alert.alert("Delete device?", `Remove ${device.name} from your home?`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: () => {
          void api.deleteDevice(device.id).then(() => {
            setDevices((current) => current.filter((item) => item.id !== device.id));
            setToast(`${device.name} deleted.`);
          }).catch((error: unknown) => {
            setToast(error instanceof ApiError ? error.message : "Unable to delete device.");
          });
        },
      },
    ]);
  }

  async function sendNora(promptText = noraInput) {
    const prompt = promptText.trim();
    if (!prompt) return;
    setNoraMessages((current) => [
      ...current,
      { from: "you", text: prompt },
    ]);
    setNoraInput("");

    if (isAssistantGreeting(prompt)) {
      respondAsNora("Hello! I’m listening. What would you like me to do?");
      return;
    }

    const command = parseVoiceCommand(prompt);
    if (!command) {
      respondAsNora("I can control lights, fans, and curtains. Try “Hey Method, switch on the living room light.”");
      return;
    }

    const backendTargets = matchVoiceTargets(devices, command);
    const demoTargets = simulation ? matchVoiceTargets(simDevices, command) : [];
    const candidates = backendTargets.length ? backendTargets : demoTargets;
    if (!candidates.length) {
      respondAsNora(`I couldn’t find a ${command.kind} to control. Check that it’s registered and online.`);
      return;
    }
    if (candidates.some((device) => !device.online)) {
      const offline = candidates.filter((device) => !device.online).map((device) => device.name);
      respondAsNora(`${offline.join(", ")} ${offline.length === 1 ? "is" : "are"} offline, so I didn’t send a command.`);
      return;
    }
    if (candidates.length > 1 && !command.all) {
      respondAsNora(`Which ${command.kind}? I found ${candidates.map((device) => device.name).join(" and ")}. Please include a device name or room.`);
      return;
    }

    const selected = command.all ? candidates : candidates.slice(0, 1);
    const outcomes: string[] = [];
    for (const device of selected) {
      const kind = voiceDeviceKind(device.device_type);
      if (isSimulated(device)) {
        const power = command.action === "on";
        const updated = {
          ...device,
          power,
          status: power ? "On" : "Off",
          updated_at: new Date().toISOString(),
        };
        setSimDevices((current) => current.map((item) => item.id === device.id ? updated : item));
        setEvents((current) => [{
          type: "device_state" as const,
          device_id: device.id,
          status: updated.status,
          timestamp: updated.updated_at,
        }, ...current].slice(0, 80));
        outcomes.push(`${device.name} ${power ? "turned on" : "turned off"} in the local demo`);
        continue;
      }

      try {
        const response = await api.sendCommand(device.id, {
          command: kind === "curtain" ? command.action : "set_power",
          ...(kind === "curtain" ? {} : { parameters: { enabled: command.action === "on" } }),
        });
        if (response.state) {
          setDevices((current) => current.map((item) => item.id === device.id
            ? {
              ...item,
              state: response.state,
              online: response.online ?? item.online,
              status: kind === "curtain"
                ? (response.state?.position === 100 ? "Open" : response.state?.position === 0 ? "Closed" : "Partially open")
                : response.state?.power ? "On" : "Off",
            }
            : item));
          outcomes.push(kind === "curtain"
            ? `${device.name} ${command.action === "open" ? "opened" : "closed"}`
            : `${device.name} turned ${command.action}`);
        } else {
          outcomes.push(`Command sent to ${device.name}; waiting for device confirmation`);
        }
      } catch (error) {
        outcomes.push(`Could not control ${device.name}: ${error instanceof ApiError ? error.message : "backend unavailable"}`);
      }
    }
    respondAsNora(outcomes.join(". "));
  }

  function respondAsNora(message: string) {
    setNoraMessages((current) => [...current, { from: "nora", text: message }]);
    Speech.speak(message, { language: "en-US" });
  }

  async function startVoiceInput() {
    if (isListening) {
      ExpoSpeechRecognitionModule.stop();
      return;
    }
    if (!ExpoSpeechRecognitionModule.isRecognitionAvailable()) {
      const message = "Speech recognition is unavailable on this device. You can type a command instead.";
      setVoiceStatus(message);
      setToast(message);
      return;
    }
    try {
      const permission = await ExpoSpeechRecognitionModule.requestPermissionsAsync();
      if (!permission.granted) {
        const message = "Microphone and speech-recognition permission are required for voice commands.";
        setVoiceStatus(message);
        setToast(message);
        return;
      }
      setVoiceStatus("Listening…");
      ExpoSpeechRecognitionModule.start({
        lang: "en-US",
        interimResults: true,
        continuous: false,
      });
    } catch {
      const message = "Couldn’t start voice input. Try again or type your command.";
      setVoiceStatus(message);
      setToast(message);
    }
  }

  const currentPage = navigation.find((item) => item.id === section)?.label ?? "Home";
  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" />
      <View style={styles.app}>
        <View style={styles.topbar}>
          <View style={styles.brandRow}>
            <View style={styles.brandGlyph}><View style={styles.brandGlyphInner} /></View>
            <View><Text style={styles.brand}>NEXORA</Text><Text style={styles.brandCaption}>HOME INTELLIGENCE</Text></View>
          </View>
          <View style={styles.topbarRight}>
            <View style={[styles.connection, apiStatus === "connected" ? styles.connectionOn : styles.connectionOff]}><View style={styles.statusDot} /><Text style={styles.connectionText}>API {apiStatus}</Text></View>
            <Pressable style={styles.bellButton} accessibilityLabel="Open notifications" onPress={() => setNoticeVisible(true)}>
              <Ionicons name="notifications-outline" size={20} color={colors.ink} />
              {notifications.length > 0 && <View style={styles.bellCount}><Text style={styles.bellCountText}>{Math.min(notifications.length, 9)}</Text></View>}
            </Pressable>
          </View>
        </View>
        <View style={styles.pageTitleBar}><Text style={styles.pageKicker}>SMART HOME / {currentPage.toUpperCase()}</Text><Text style={styles.pageTitle}>{currentPage}</Text></View>
        <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          {section === "home" && <HomeScreen devices={visibleDevices} events={events} simulation={simulation} socketStatus={socketStatus} onControl={control} onNavigate={setSection} />}
          {section === "devices" && <DevicesScreen devices={visibleDevices} onControl={control} onAdd={() => setAddVisible(true)} onDelete={deleteDevice} />}
          {section === "activity" && <ActivityScreen devices={visibleDevices} events={events} />}
          {section === "automations" && <AutomationsScreen
            devices={automationDevices}
            selectedDevice={selectedAutomationDevice}
            selectedDeviceId={selectedAutomationDevice?.id ?? ""}
            rules={automations}
            name={automationName}
            time={automationTime}
            loading={automationLoading}
            busy={automationBusy}
            onName={setAutomationName}
            onTime={setAutomationTime}
            onSelectDevice={(id) => {
              setAutomationDeviceId(id);
              const device = automationDevices.find((item) => item.id === id);
              setAutomationCommand(device?.device_type.toLowerCase().includes("curtain") ? "open" : "turn_on");
            }}
            command={automationCommand}
            onCommand={setAutomationCommand}
            onCreate={() => void createAutomation()}
            onToggle={(rule) => void toggleAutomation(rule)}
            onDelete={(rule) => void removeAutomation(rule)}
          />}
          {section === "nora" && <NoraScreen messages={noraMessages} value={noraInput} onChange={setNoraInput} onSend={() => void sendNora()} onMic={() => void startVoiceInput()} voiceStatus={voiceStatus} isListening={isListening} />}
          {section === "settings" && <SettingsScreen apiStatus={apiStatus} socketStatus={socketStatus} simulation={simulation} onToggleSimulation={() => setSimulation((value) => !value)} />}
        </ScrollView>
        <View style={styles.bottomNav}>
          {navigation.map((item) => {
            const selected = item.id === section;
            return <Pressable key={item.id} onPress={() => setSection(item.id)} style={styles.navButton} accessibilityRole="button" accessibilityState={{ selected }} accessibilityLabel={item.label}>
              <Ionicons name={item.icon} size={19} color={selected ? colors.cyan : "#AAA7A0"} />
              <Text style={[styles.navLabel, selected && styles.navLabelActive]}>{item.label}</Text>
            </Pressable>;
          })}
        </View>
      </View>
      <Modal visible={addVisible} transparent animationType="fade" onRequestClose={() => setAddVisible(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.modalBackdrop}>
          <View style={styles.modal}>
            <View style={styles.modalHead}><Text style={styles.modalTitle}>Register a device</Text><Pressable onPress={() => setAddVisible(false)} accessibilityLabel="Close"><Ionicons name="close" size={22} color={colors.ink} /></Pressable></View>
            <Text style={styles.fieldLabel}>Name</Text><TextInput value={name} onChangeText={setName} placeholder="Hallway light" placeholderTextColor="#9AA6AE" style={styles.input} />
            <Text style={styles.fieldLabel}>Room</Text><TextInput value={room} onChangeText={setRoom} placeholder="Hallway" placeholderTextColor="#9AA6AE" style={styles.input} />
            <Text style={styles.fieldLabel}>Device type</Text><TextInput value={deviceType} onChangeText={setDeviceType} placeholder="smart_light" placeholderTextColor="#9AA6AE" style={styles.input} autoCapitalize="none" />
            <Pressable style={styles.simulatorOption} onPress={() => setSimulatedDevice((value) => !value)} accessibilityRole="checkbox" accessibilityState={{ checked: simulatedDevice }}>
              <Ionicons name={simulatedDevice ? "checkbox" : "square-outline"} size={17} color={colors.cyan} />
              <Text style={styles.formHint}>Run as a backend simulated device</Text>
            </Pressable>
            <Text style={styles.formHint}>Backend simulated state persists and updates live. Local demo devices remain separate.</Text>
            <Pressable style={styles.primaryButton} onPress={() => void addDevice()}><Text style={styles.primaryButtonText}>Create device</Text></Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
      <Modal visible={noticeVisible} transparent animationType="slide" onRequestClose={() => setNoticeVisible(false)}>
        <View style={styles.noticeBackdrop}><View style={styles.noticeSheet}>
          <View style={styles.modalHead}><View><Text style={styles.modalTitle}>Notifications</Text><Text style={styles.mutedText}>In-app session alerts</Text></View><Pressable onPress={() => setNoticeVisible(false)}><Ionicons name="close" size={22} color={colors.ink} /></Pressable></View>
          {notifications.length ? notifications.slice(0, 6).map((item) => <View style={styles.notificationRow} key={item.id}><Ionicons name="notifications-outline" size={16} color={colors.cyan} /><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{item.title}</Text><Text style={styles.mutedText}>{item.detail}</Text></View></View>) : <Text style={styles.mutedText}>No new alerts. Push delivery is not configured.</Text>}
        </View></View>
      </Modal>
      {!!toast && <Pressable style={styles.toast} onPress={() => setToast("")}><Text style={styles.toastText}>{toast}</Text></Pressable>}
    </SafeAreaView>
  );
}

function HomeScreen({ devices, events, simulation, socketStatus, onControl, onNavigate }: {
  devices: AnyDevice[]; events: DeviceEvent[]; simulation: boolean; socketStatus: string; onControl: (device: AnyDevice) => void; onNavigate: (section: Section) => void;
}) {
  const rooms = [...new Set(devices.map((device) => device.room || "Unassigned"))];
  const simulatedSensors = devices.filter(isSimulated).flatMap((device) => device.sensor_readings.map((reading) => ({ ...reading, room: device.room })));
  const liveSensors = events.filter((event) => event.type === "device_sensor").map((event) => ({
    name: event.name ?? event.sensor_type ?? "Sensor",
    reading: event.reading ?? null,
    unit: event.unit ?? null,
    room: devices.find((device) => device.id === event.device_id)?.room ?? "Home",
  }));
  const sensors = [...liveSensors, ...simulatedSensors];
  const quick = devices.filter((device) => /light|fan/i.test(device.device_type)).slice(0, 4);
  return <>
    <View style={styles.heroCard}>
      <View style={styles.heroGlow} /><Text style={styles.eyebrowLight}>YOUR HOME, IN SYNC</Text><Text style={styles.heroTitle}>A smarter home,{"\n"}at a glance.</Text><Text style={styles.heroText}>Control your space with a little more ease.</Text>
      <View style={styles.heroStats}><View><Text style={styles.heroStatValue}>{devices.filter((device) => device.online).length}/{devices.length}</Text><Text style={styles.heroStatLabel}>DEVICES ONLINE</Text></View><View style={styles.statDivider} /><View><Text style={styles.heroStatValue}>{rooms.length}</Text><Text style={styles.heroStatLabel}>ACTIVE ROOMS</Text></View><View style={styles.statDivider} /><View><Text style={styles.heroStatValue}>{simulation ? "LOCAL" : "LIVE"}</Text><Text style={styles.heroStatLabel}>DEVICE MODE</Text></View></View>
    </View>
    <SectionHeader title="Quick controls" action="See all" onAction={() => onNavigate("devices")} />
    {quick.length ? <View style={styles.deviceGrid}>{quick.map((device) => <DeviceTile key={device.id} device={device} onControl={() => onControl(device)} />)}</View> : <EmptyCard text="No devices yet. Enable the local simulator or add a device." />}
    <SectionHeader title="Room overview" action={`${rooms.length} rooms`} onAction={() => onNavigate("devices")} />
    <View style={styles.panel}>{rooms.map((room) => {
      const count = devices.filter((device) => (device.room || "Unassigned") === room).length;
      return <Pressable key={room} style={styles.roomItem} onPress={() => onNavigate("devices")}><View style={styles.roomIcon}><Ionicons name="home-outline" size={17} color={colors.cyan} /></View><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{room}</Text><Text style={styles.mutedText}>{count} devices</Text></View><Ionicons name="chevron-forward" size={17} color="#9AA6AE" /></Pressable>;
    })}</View>
    <SectionHeader title="Live readings" action={socketStatus === "connected" ? "LIVE" : "WAITING"} />
    {sensors.length ? <View style={styles.panel}>{sensors.slice(0, 2).map((reading) => <View key={reading.name} style={styles.sensorItem}><Ionicons name="thermometer-outline" size={18} color="#4382C5" /><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{reading.name}</Text><Text style={styles.mutedText}>{reading.room}</Text></View><Text style={styles.sensorValue}>{reading.reading}{reading.unit}</Text></View>)}</View> : <EmptyCard text="Sensor history is not available through the current API." />}
    <Pressable style={styles.noraPromo} onPress={() => onNavigate("nora")}><View style={styles.noraPromoOrb}><Ionicons name="sparkles" size={19} color="#8BEEFB" /></View><View style={{ flex: 1 }}><Text style={styles.noraPromoTitle}>Meet NORA</Text><Text style={styles.noraPromoText}>Open the local assistant preview</Text></View><Ionicons name="arrow-forward" size={18} color="#D9F7FF" /></Pressable>
    <Pressable style={[styles.outlineButton, { marginTop: 10 }]} onPress={() => onNavigate("automations")}><Ionicons name="flash-outline" size={17} color={colors.cyan} /><Text style={styles.outlineButtonText}>Automation schedules</Text><Ionicons name="arrow-forward" size={15} color={colors.cyan} /></Pressable>
  </>;
}

function SectionHeader({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  return <View style={styles.sectionHeader}><Text style={styles.sectionTitle}>{title}</Text>{action && <Pressable onPress={onAction}><Text style={styles.sectionAction}>{action}</Text></Pressable>}</View>;
}

function DeviceTile({ device, onControl, onDelete }: { device: AnyDevice; onControl: () => void; onDelete?: () => void }) {
  const sensor = isSimulated(device) ? device.sensor_readings[0] : undefined;
  const actuator = /light|fan|curtain/i.test(device.device_type);
  const on = onState(device);
  return <View style={styles.deviceTile}>
    <View style={styles.tileTop}><View style={[styles.deviceGlyph, on && styles.deviceGlyphOn]}><Ionicons name={deviceIcon(device.device_type)} size={20} color={on ? colors.cyan : "#AAA7A0"} /></View><View style={styles.tileActions}>{onDelete && !isSimulated(device) && <Pressable onPress={onDelete} accessibilityLabel={`Delete ${device.name}`}><Ionicons name="trash-outline" size={15} color="#AAA7A0" /></Pressable>}<View style={[styles.onlineDot, { backgroundColor: device.online ? "#4BC08A" : "#77787B" }]} /><Text style={styles.onlineText}>{device.online ? "Online" : "Offline"}</Text></View></View>
    <Text style={styles.deviceName} numberOfLines={1}>{device.name}</Text><Text style={styles.deviceRoom} numberOfLines={1}>{device.room || "Unassigned"}{isSimulated(device) ? " · DEMO" : ""}{!isSimulated(device) && device.simulated ? " · SIM" : ""}</Text>
    {sensor ? <View style={styles.sensorInline}><Text style={styles.sensorInlineValue}>{sensor.reading}{sensor.unit}</Text><Text style={styles.mutedText}>{sensor.name}</Text></View> : <Text style={styles.deviceState}>{deviceStateLabel(device)}</Text>}
    {actuator && <Pressable style={[styles.controlButton, on && styles.controlButtonOn]} onPress={onControl}><Text style={[styles.controlText, on && styles.controlTextOn]}>{controlLabel(device).toUpperCase()}</Text><Ionicons name="power-outline" size={15} color={on ? colors.cyan : colors.mutedInk} /></Pressable>}
  </View>;
}

function DevicesScreen({ devices, onControl, onAdd, onDelete }: { devices: AnyDevice[]; onControl: (device: AnyDevice) => void; onAdd: () => void; onDelete: (device: AnyDevice) => void }) {
  const rooms = [...new Set(devices.map((device) => device.room || "Unassigned"))];
  return <>
    <View style={styles.screenIntro}><Text style={styles.eyebrow}>DEVICE MANAGEMENT</Text><Text style={styles.screenTitle}>Your devices</Text><Text style={styles.mutedText}>Room-by-room controls · {devices.length} devices</Text></View>
    <Pressable style={styles.outlineButton} onPress={onAdd}><Ionicons name="add" size={18} color={colors.cyan} /><Text style={styles.outlineButtonText}>Register device</Text></Pressable>
    {rooms.map((room) => <View key={room}><SectionHeader title={room} action={`${devices.filter((device) => (device.room || "Unassigned") === room).length}`} /><View style={styles.deviceGrid}>{devices.filter((device) => (device.room || "Unassigned") === room).map((device) => <DeviceTile key={device.id} device={device} onControl={() => onControl(device)} onDelete={() => onDelete(device)} />)}</View></View>)}
    {!devices.length && <EmptyCard text="No devices loaded. Check the API or enable the simulator in Settings." />}
  </>;
}

function ActivityScreen({ devices, events }: { devices: AnyDevice[]; events: DeviceEvent[] }) {
  return <>
    <View style={styles.screenIntro}><Text style={styles.eyebrow}>LIVE SESSION</Text><Text style={styles.screenTitle}>Activity & safety</Text><Text style={styles.mutedText}>Session events only · not persisted history</Text></View>
    <View style={styles.panel}>
      <Text style={styles.cardHeading}>Recent activity</Text>
      {events.length ? events.slice(0, 20).map((event, index) => {
        const device = devices.find((item) => item.id === event.device_id);
        return <View key={`${event.timestamp}-${index}`} style={styles.eventRow}><View style={styles.eventGlyph}><Ionicons name="pulse-outline" size={16} color={colors.cyan} /></View><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{event.type.replaceAll("_", " ")}</Text><Text style={styles.mutedText}>{device?.name ?? event.device_id ?? event.message ?? "Backend event"}{event.reading !== undefined ? ` · ${event.reading}${event.unit ?? ""}` : ""}</Text></View></View>;
      }) : <EmptyCard text="Simulator and WebSocket events will appear here." />}
    </View>
    <View style={[styles.panel, { marginTop: 14 }]}><View style={styles.cardHeadingRow}><Text style={styles.cardHeading}>Security center</Text><Ionicons name="shield-checkmark-outline" size={17} color="#218353" /></View><Text style={styles.mutedText}>The security-events model has no read endpoint yet. No live security status is available.</Text></View>
    <View style={[styles.panel, { marginTop: 14 }]}><Text style={styles.cardHeading}>Push notifications</Text><Text style={styles.mutedText}>In-app alert preview only. Push delivery is not configured.</Text></View>
  </>;
}

function AutomationsScreen({
  devices,
  selectedDevice,
  selectedDeviceId,
  rules,
  name,
  time,
  command,
  loading,
  busy,
  onName,
  onTime,
  onSelectDevice,
  onCommand,
  onCreate,
  onToggle,
  onDelete,
}: {
  devices: Device[];
  selectedDevice: Device | undefined;
  selectedDeviceId: string;
  rules: AutomationRule[];
  name: string;
  time: string;
  command: AutomationCreate["action"]["command"];
  loading: boolean;
  busy: boolean;
  onName: (value: string) => void;
  onTime: (value: string) => void;
  onSelectDevice: (id: string) => void;
  onCommand: (value: AutomationCreate["action"]["command"]) => void;
  onCreate: () => void;
  onToggle: (rule: AutomationRule) => void;
  onDelete: (rule: AutomationRule) => void;
}) {
  const isCurtain = selectedDevice?.device_type.toLowerCase().includes("curtain") ?? false;
  const selectedCommand = isCurtain
    ? (command === "close" ? "close" : "open")
    : (command === "turn_off" ? "turn_off" : "turn_on");
  return <>
    <View style={styles.screenIntro}><Text style={styles.eyebrow}>HOME ROUTINES</Text><Text style={styles.screenTitle}>Automations</Text><Text style={styles.mutedText}>Schedules are saved to your connected NEXORA backend.</Text></View>
    <View style={styles.panel}>
      <Text style={styles.cardHeading}>Create an automation</Text>
      <Text style={styles.fieldLabel}>Name</Text>
      <TextInput accessibilityLabel="Name" style={styles.input} value={name} onChangeText={onName} placeholder="Weekday lights" placeholderTextColor={colors.mutedInk} />
      <Text style={styles.fieldLabel}>Time</Text>
      <TextInput accessibilityLabel="Time" style={styles.input} value={time} onChangeText={onTime} placeholder="19:00" placeholderTextColor={colors.mutedInk} keyboardType="numbers-and-punctuation" />
      <Text style={styles.fieldLabel}>Device</Text>
      {devices.length
        ? <View style={styles.automationChoices}>{devices.map((device) => <Pressable key={device.id} onPress={() => onSelectDevice(device.id)} style={[styles.automationChoice, selectedDeviceId === device.id && styles.automationChoiceSelected]}><Text style={[styles.automationChoiceText, selectedDeviceId === device.id && styles.automationChoiceTextSelected]}>{device.name}</Text></Pressable>)}</View>
        : <Text style={styles.formHint}>No supported backend devices are available. Register a light, fan, or curtain first.</Text>}
      {selectedDevice && <>
        <Text style={styles.fieldLabel}>Action</Text>
        <View style={styles.automationChoices}>{(isCurtain ? ["open", "close"] as const : ["turn_on", "turn_off"] as const).map((action) => <Pressable key={action} onPress={() => onCommand(action)} style={[styles.automationChoice, selectedCommand === action && styles.automationChoiceSelected]}><Text style={[styles.automationChoiceText, selectedCommand === action && styles.automationChoiceTextSelected]}>{isCurtain ? action : action === "turn_on" ? "Turn on" : "Turn off"}</Text></Pressable>)}</View>
      </>}
      <Text style={styles.formHint}>Repeats every day · uses this device’s local time zone.</Text>
      <Pressable disabled={busy || !selectedDevice} style={[styles.primaryButton, (busy || !selectedDevice) && styles.buttonDisabled]} onPress={onCreate}><Text style={styles.primaryButtonText}>{busy ? "Saving..." : "Save schedule"}</Text></Pressable>
    </View>
    <SectionHeader title="Saved schedules" action={`${rules.length}`} />
    {loading && <Text style={styles.mutedText}>Loading schedules...</Text>}
    {!loading && !rules.length && <EmptyCard text="No schedules yet. Create one above to run an action automatically." />}
    {rules.map((rule) => <View key={rule.id} style={styles.savedRule}>
      <View style={styles.savedRuleInfo}><Text style={styles.rowTitle}>{rule.name}</Text><Text style={styles.mutedText}>{rule.trigger.time} · {rule.action.command.replace("_", " ")} · {rule.trigger.timezone}</Text>{rule.last_error ? <Text style={styles.formError}>{rule.last_error}</Text> : null}</View>
      <Pressable accessibilityRole="switch" accessibilityLabel={`${rule.enabled ? "Pause" : "Enable"} ${rule.name}`} accessibilityState={{ checked: rule.enabled }} disabled={busy} onPress={() => onToggle(rule)} style={[styles.switchTrack, rule.enabled && styles.switchTrackOn]}><View style={[styles.switchThumb, rule.enabled && styles.switchThumbOn]} /></Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={`Delete ${rule.name}`} disabled={busy} onPress={() => onDelete(rule)}><Ionicons name="trash-outline" size={17} color={colors.mutedInk} /></Pressable>
    </View>)}
  </>;
}

function NoraScreen({ messages, value, onChange, onSend, onMic, voiceStatus, isListening }: {
  messages: { from: string; text: string }[];
  value: string;
  onChange: (text: string) => void;
  onSend: () => void;
  onMic: () => void;
  voiceStatus: string;
  isListening: boolean;
}) {
  return <>
    <View style={styles.noraHero}><View style={styles.noraHalo}><Ionicons name="sparkles" size={28} color="#F5C06A" /></View><Text style={styles.eyebrowLight}>NEXORA HOME COMPANION</Text><Text style={styles.noraHeading}>Hello, I’m NORA.</Text><Text style={styles.heroText}>You can call me Method. Tap the microphone and say “Hey Method” or “Hello Method” with your command.</Text></View>
    <View style={[styles.panel, { marginTop: 14 }]}>
      <FlatList
        data={messages}
        keyExtractor={(_, index) => `nora-${index}`}
        scrollEnabled={false}
        renderItem={({ item }) => <View style={[styles.chatMessage, item.from === "you" && styles.chatUser]}><View style={styles.chatAvatar}><Text style={styles.chatAvatarText}>{item.from === "you" ? "P" : "N"}</Text></View><View style={styles.chatBubble}><Text style={styles.chatLabel}>{item.from === "you" ? "YOU" : "NORA · LOCAL"}</Text><Text style={styles.chatText}>{item.text}</Text></View></View>}
      />
      <View style={styles.chatInputRow}><Pressable style={[styles.voiceButton, isListening && styles.voiceButtonActive]} onPress={onMic} accessibilityRole="button" accessibilityLabel={isListening ? "Stop listening" : "Start voice command"} accessibilityState={{ selected: isListening }}><Ionicons name={isListening ? "stop" : "mic"} size={17} color={isListening ? "white" : colors.cyan} /></Pressable><TextInput style={styles.chatInput} value={value} onChangeText={onChange} placeholder="Hey Method, turn on the living room light" placeholderTextColor="#9AA6AE" onSubmitEditing={onSend} /><Pressable style={styles.sendButton} onPress={onSend}><Ionicons name="arrow-up" size={18} color="#21170C" /></Pressable></View>
      <Text style={styles.formHint}>{voiceStatus} · no AI service; audio and transcripts are not sent to the NEXORA backend.</Text>
    </View>
  </>;
}

function SettingsScreen({ apiStatus, socketStatus, simulation, onToggleSimulation }: {
  apiStatus: string; socketStatus: string; simulation: boolean; onToggleSimulation: () => void;
}) {
  return <>
    <View style={styles.screenIntro}><Text style={styles.eyebrow}>PREFERENCES</Text><Text style={styles.screenTitle}>Settings</Text><Text style={styles.mutedText}>Connections and local development</Text></View>
    <View style={styles.panel}>
      <Text style={styles.cardHeading}>Connection health</Text>
      <SettingItem icon="server-outline" title="FastAPI backend" detail={apiBase} status={apiStatus} />
      <SettingItem icon="radio-outline" title="WebSocket" detail="/ws live device events" status={socketStatus} />
      <SettingItem icon="hardware-chip-outline" title="MQTT broker" detail="Not reported by API · remains disabled unless configured" status="unknown" />
    </View>
    <View style={[styles.panel, { marginTop: 14 }]}>
      <Text style={styles.cardHeading}>Development mode</Text>
      <Pressable style={styles.settingToggle} onPress={onToggleSimulation} accessibilityRole="switch" accessibilityState={{ checked: simulation }}><View style={{ flex: 1 }}><Text style={styles.rowTitle}>Local simulator</Text><Text style={styles.mutedText}>In-memory only · no backend writes</Text></View><View style={[styles.switchTrack, simulation && styles.switchTrackOn]}><View style={[styles.switchThumb, simulation && styles.switchThumbOn]} /></View></Pressable>
      <View style={styles.settingToggle}><View style={{ flex: 1 }}><Text style={styles.rowTitle}>Push notifications</Text><Text style={styles.mutedText}>UI preview only · delivery not configured</Text></View><Text style={styles.previewText}>PREVIEW</Text></View>
    </View>
    <View style={styles.privacyNote}><Ionicons name="lock-closed-outline" size={15} color={colors.cyan} /><Text style={styles.mutedText}>Real-device controls use the existing API. The simulator never writes its sample devices to Neon.</Text></View>
  </>;
}

function SettingItem({ icon, title, detail, status }: { icon: keyof typeof Ionicons.glyphMap; title: string; detail: string; status: string }) {
  const connected = status === "connected";
  return <View style={styles.settingItem}><Ionicons name={icon} size={17} color={colors.cyan} /><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{title}</Text><Text style={styles.mutedText}>{detail}</Text></View><Text style={[styles.settingStatus, connected ? styles.settingStatusOn : styles.settingStatusOff]}>{status}</Text></View>;
}

function EmptyCard({ text }: { text: string }) {
  return <View style={styles.emptyCard}><Ionicons name="information-circle-outline" size={20} color="#718899" /><Text style={styles.mutedText}>{text}</Text></View>;
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.charcoal },
  app: { flex: 1, backgroundColor: colors.paper },
  topbar: { minHeight: 58, paddingHorizontal: 16, flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: colors.charcoal },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 9 },
  brandGlyph: { width: 29, height: 29, borderRadius: 10, borderWidth: 1, borderColor: colors.cyan, backgroundColor: "#332719", alignItems: "center", justifyContent: "center" },
  brandGlyphInner: { width: 10, height: 10, borderWidth: 2, borderColor: colors.cyan, transform: [{ rotate: "45deg" }] },
  brand: { color: "white", fontWeight: "800", letterSpacing: 2, fontSize: 12 },
  brandCaption: { color: "#96AAB8", fontSize: 7, letterSpacing: 1.3, marginTop: 2 },
  topbarRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  connection: { flexDirection: "row", alignItems: "center", gap: 5, borderRadius: 14, paddingHorizontal: 8, paddingVertical: 6 },
  connectionOn: { backgroundColor: "#183A34" },
  connectionOff: { backgroundColor: "#343538" },
  statusDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#50D597" },
  connectionText: { color: "#E6F1F4", fontSize: 8, textTransform: "capitalize" },
  bellButton: { position: "relative", width: 33, height: 33, borderRadius: 11, backgroundColor: colors.surfaceSoft, alignItems: "center", justifyContent: "center" },
  bellCount: { position: "absolute", top: -3, right: -3, minWidth: 14, height: 14, borderRadius: 7, backgroundColor: colors.cyan, alignItems: "center", justifyContent: "center" },
  bellCountText: { color: "white", fontSize: 8, fontWeight: "700" },
  pageTitleBar: { paddingHorizontal: 17, paddingTop: 14, paddingBottom: 10, backgroundColor: colors.charcoal },
  pageKicker: { color: "#81A0B0", fontSize: 8, letterSpacing: 1.3, fontWeight: "700" },
  pageTitle: { color: "white", fontSize: 19, fontWeight: "700", marginTop: 4 },
  scrollContent: { paddingHorizontal: 15, paddingTop: 15, paddingBottom: 25 },
  heroCard: { overflow: "hidden", position: "relative", padding: 20, borderRadius: 19, backgroundColor: colors.charcoalSoft, borderWidth: 1, borderColor: colors.border },
  heroGlow: { position: "absolute", width: 180, height: 180, borderRadius: 90, right: -70, top: -90, backgroundColor: "#5B3A1C", opacity: 0.58 },
  eyebrowLight: { color: "#F5C06A", fontSize: 8, letterSpacing: 1.3, fontWeight: "700" },
  heroTitle: { marginTop: 12, color: "white", fontSize: 26, lineHeight: 31, fontWeight: "700", letterSpacing: -0.6 },
  heroText: { marginTop: 7, color: "#B9C9D1", fontSize: 10, lineHeight: 16 },
  heroStats: { marginTop: 22, paddingTop: 14, borderTopWidth: 1, borderTopColor: "rgba(255,255,255,.12)", flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  heroStatValue: { color: "#F3FCFF", fontSize: 16, fontWeight: "700" },
  heroStatLabel: { marginTop: 4, color: "#93ACB8", fontSize: 7, letterSpacing: 0.7, fontWeight: "700" },
  statDivider: { height: 28, width: 1, backgroundColor: "rgba(255,255,255,.14)" },
  sectionHeader: { minHeight: 34, marginTop: 18, marginBottom: 8, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  sectionTitle: { color: colors.ink, fontSize: 14, fontWeight: "700", letterSpacing: -0.2 },
  sectionAction: { color: colors.cyan, fontSize: 9, fontWeight: "700" },
  deviceGrid: { flexDirection: "row", flexWrap: "wrap", gap: 9 },
  deviceTile: { width: "48.5%", minHeight: 151, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  tileTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  deviceGlyph: { width: 34, height: 34, borderRadius: 11, backgroundColor: colors.surfaceSoft, alignItems: "center", justifyContent: "center" },
  deviceGlyphOn: { backgroundColor: "#382A1B" },
  onlineDot: { width: 7, height: 7, borderRadius: 4 },
  tileActions: { flexDirection: "row", alignItems: "center", gap: 8 },
  onlineText: { color: colors.mutedInk, fontSize: 7 },
  deviceName: { marginTop: 12, color: colors.ink, fontSize: 11, fontWeight: "700" },
  deviceRoom: { marginTop: 3, color: colors.mutedInk, fontSize: 8 },
  deviceState: { marginTop: 11, color: colors.mutedInk, fontSize: 8 },
  controlButton: { marginTop: 8, height: 28, paddingHorizontal: 8, borderRadius: 8, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.paper, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  controlButtonOn: { borderColor: "#73512E", backgroundColor: "#302519" },
  controlText: { color: colors.mutedInk, fontSize: 8, fontWeight: "800", letterSpacing: 0.7 },
  controlTextOn: { color: colors.cyan },
  sensorInline: { marginTop: 7 },
  sensorInlineValue: { color: colors.ink, fontSize: 17, fontWeight: "700" },
  panel: { padding: 14, borderRadius: 15, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  roomItem: { flexDirection: "row", alignItems: "center", minHeight: 48, gap: 9, borderBottomWidth: 1, borderBottomColor: colors.border },
  roomIcon: { width: 31, height: 31, borderRadius: 10, backgroundColor: "#332719", alignItems: "center", justifyContent: "center" },
  rowTitle: { color: colors.ink, fontSize: 10, fontWeight: "700" },
  mutedText: { color: colors.mutedInk, fontSize: 8, lineHeight: 13, marginTop: 3 },
  sensorItem: { minHeight: 48, flexDirection: "row", alignItems: "center", gap: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  sensorValue: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  noraPromo: { marginTop: 15, minHeight: 74, padding: 13, borderRadius: 15, backgroundColor: colors.charcoalSoft, flexDirection: "row", alignItems: "center", gap: 11 },
  noraPromoOrb: { width: 39, height: 39, borderRadius: 14, backgroundColor: "#332719", alignItems: "center", justifyContent: "center" },
  noraPromoTitle: { color: "white", fontSize: 12, fontWeight: "700" },
  noraPromoText: { color: "#AFC0CA", fontSize: 8, marginTop: 4 },
  bottomNav: { minHeight: 58, paddingHorizontal: 4, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.charcoal, flexDirection: "row", alignItems: "center", justifyContent: "space-around" },
  navButton: { flex: 1, alignItems: "center", justifyContent: "center", gap: 3, minHeight: 52 },
  navLabel: { color: "#798794", fontSize: 7 },
  navLabelActive: { color: colors.cyan, fontWeight: "700" },
  screenIntro: { marginBottom: 9 },
  eyebrow: { color: colors.mutedInk, fontSize: 8, letterSpacing: 1.1, fontWeight: "700" },
  screenTitle: { marginTop: 5, marginBottom: 4, color: colors.ink, fontSize: 23, fontWeight: "700", letterSpacing: -0.5 },
  outlineButton: { height: 40, marginVertical: 8, borderRadius: 10, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7 },
  outlineButtonText: { color: colors.cyan, fontSize: 10, fontWeight: "700" },
  cardHeading: { marginBottom: 10, color: colors.ink, fontSize: 13, fontWeight: "700" },
  cardHeadingRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  eventRow: { minHeight: 49, flexDirection: "row", alignItems: "center", gap: 9, borderBottomWidth: 1, borderBottomColor: colors.border },
  eventGlyph: { width: 30, height: 30, borderRadius: 10, backgroundColor: "#332719", alignItems: "center", justifyContent: "center" },
  automationHero: { padding: 20, borderRadius: 17, backgroundColor: colors.charcoalSoft, borderWidth: 1, borderColor: colors.border },
  automationTitle: { marginTop: 12, color: "white", fontSize: 19, fontWeight: "700" },
  automationBody: { marginTop: 7, color: "#B8C8D1", fontSize: 9, lineHeight: 15 },
  ruleRow: { minHeight: 58, marginTop: 10, paddingHorizontal: 12, borderRadius: 13, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, flexDirection: "row", alignItems: "center", gap: 9 },
  ruleText: { flex: 1, color: colors.ink, fontSize: 9 },
  disabledTrack: { width: 27, height: 15, padding: 2, borderRadius: 9, backgroundColor: "#D8DFE4" },
  disabledTrackInner: { width: 11, height: 11, borderRadius: 6, backgroundColor: "white" },
  noraHero: { alignItems: "center", padding: 21, borderRadius: 18, backgroundColor: colors.charcoalSoft },
  noraHalo: { width: 62, height: 62, marginBottom: 13, borderRadius: 31, borderWidth: 1, borderColor: "#73512E", backgroundColor: "#332719", alignItems: "center", justifyContent: "center" },
  noraHeading: { marginTop: 8, color: "white", fontSize: 22, fontWeight: "700" },
  chatMessage: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginVertical: 7 },
  chatUser: { flexDirection: "row-reverse" },
  chatAvatar: { width: 27, height: 27, borderRadius: 9, backgroundColor: "#E6F7F9", alignItems: "center", justifyContent: "center" },
  chatAvatarText: { color: "#087F95", fontSize: 10, fontWeight: "700" },
  chatBubble: { flex: 1, padding: 9, borderRadius: 11, backgroundColor: colors.surfaceSoft },
  chatLabel: { color: "#8B98A2", fontSize: 7, fontWeight: "700", letterSpacing: 0.7 },
  chatText: { marginTop: 4, color: colors.ink, fontSize: 9, lineHeight: 14 },
  chatInputRow: { flexDirection: "row", gap: 7, alignItems: "center", marginTop: 9, padding: 6, borderWidth: 1, borderColor: colors.border, borderRadius: 11, backgroundColor: colors.paper },
  voiceButton: { width: 33, height: 33, borderRadius: 10, backgroundColor: "#332719", alignItems: "center", justifyContent: "center" },
  voiceButtonActive: { backgroundColor: "#D64545" },
  chatInput: { flex: 1, minHeight: 35, paddingHorizontal: 8, color: colors.ink, fontSize: 9 },
  sendButton: { width: 33, height: 33, borderRadius: 10, backgroundColor: colors.cyan, alignItems: "center", justifyContent: "center" },
  formHint: { marginTop: 8, color: "#87939E", fontSize: 8 },
  simulatorOption: { marginTop: 8, flexDirection: "row", alignItems: "center", gap: 7 },
  settingItem: { minHeight: 53, flexDirection: "row", alignItems: "center", gap: 9, borderTopWidth: 1, borderTopColor: colors.border },
  settingStatus: { textTransform: "capitalize", fontSize: 8, paddingHorizontal: 7, paddingVertical: 4, borderRadius: 6 },
  settingStatusOn: { color: "#68D69D", backgroundColor: "#1B3025" },
  settingStatusOff: { color: colors.mutedInk, backgroundColor: colors.surfaceSoft },
  settingToggle: { minHeight: 56, flexDirection: "row", alignItems: "center", gap: 10, borderTopWidth: 1, borderTopColor: colors.border },
  switchTrack: { width: 34, height: 19, padding: 2, borderRadius: 10, backgroundColor: "#55565A", justifyContent: "center" },
  switchTrackOn: { backgroundColor: colors.cyan },
  switchThumb: { width: 15, height: 15, borderRadius: 8, backgroundColor: "white" },
  switchThumbOn: { alignSelf: "flex-end" },
  previewText: { color: colors.mutedInk, fontSize: 7, fontWeight: "700", letterSpacing: 0.5 },
  privacyNote: { flexDirection: "row", gap: 8, alignItems: "flex-start", marginTop: 14, padding: 12, borderRadius: 11, backgroundColor: "#29251F" },
  emptyCard: { minHeight: 75, marginTop: 8, padding: 13, borderRadius: 13, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, flexDirection: "row", gap: 8, alignItems: "center" },
  modalBackdrop: { flex: 1, padding: 18, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(10,20,29,.5)" },
  modal: { width: "100%", padding: 18, borderRadius: 17, backgroundColor: colors.surface },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 14 },
  modalTitle: { color: colors.ink, fontSize: 16, fontWeight: "700" },
  fieldLabel: { marginTop: 9, color: colors.ink, fontSize: 9, fontWeight: "700" },
  input: { height: 40, marginTop: 5, paddingHorizontal: 10, borderWidth: 1, borderColor: colors.border, borderRadius: 9, color: colors.ink, backgroundColor: colors.paper, fontSize: 10 },
  primaryButton: { height: 42, marginTop: 17, borderRadius: 10, backgroundColor: colors.cyan, alignItems: "center", justifyContent: "center" },
  primaryButtonText: { color: "#21170C", fontSize: 10, fontWeight: "700" },
  automationChoices: { flexDirection: "row", flexWrap: "wrap", gap: 7, marginTop: 7 },
  automationChoice: { paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.paper },
  automationChoiceSelected: { borderColor: colors.cyan, backgroundColor: "#332719" },
  automationChoiceText: { color: colors.mutedInk, fontSize: 9 },
  automationChoiceTextSelected: { color: colors.cyan, fontWeight: "700" },
  savedRule: { minHeight: 66, marginTop: 8, padding: 11, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, flexDirection: "row", alignItems: "center", gap: 11 },
  savedRuleInfo: { flex: 1 },
  buttonDisabled: { opacity: 0.55 },
  formError: { marginTop: 4, color: "#C04B3D", fontSize: 8 },
  noticeBackdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(10,20,29,.45)" },
  noticeSheet: { minHeight: 240, maxHeight: "70%", padding: 19, borderTopLeftRadius: 20, borderTopRightRadius: 20, backgroundColor: colors.surface },
  notificationRow: { minHeight: 48, flexDirection: "row", alignItems: "center", gap: 9, borderTopWidth: 1, borderTopColor: colors.border },
  toast: { position: "absolute", bottom: 72, left: 15, right: 15, padding: 12, borderRadius: 10, backgroundColor: "#152633", elevation: 5 },
  toastText: { color: "white", fontSize: 10 },
});

export default App;
