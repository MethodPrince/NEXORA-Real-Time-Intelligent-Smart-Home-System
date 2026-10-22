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
import { StatusBar } from "expo-status-bar";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  ApiError,
  colors,
  createDemoDevices,
  isDeviceEvent,
  NexoraApi,
  tickSimulatedSensors,
  toggleSimulatedDevice,
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
  return "simulated" in device && device.simulated;
}

function onState(device: AnyDevice) {
  return isSimulated(device)
    ? device.power
    : device.status.toLowerCase() === "on" || device.status.toLowerCase() === "active";
}

function deviceIcon(type: string): keyof typeof Ionicons.glyphMap {
  if (/fan/i.test(type)) return "sync-outline";
  if (/sensor|temperature/i.test(type)) return "thermometer-outline";
  return "bulb-outline";
}

function App() {
  const [section, setSection] = useState<Section>("home");
  const [devices, setDevices] = useState<Device[]>([]);
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
  const [noraInput, setNoraInput] = useState("");
  const [noraMessages, setNoraMessages] = useState([
    { from: "nora", text: "Hi, I’m NORA. Ask me to control the local simulated home." },
  ]);
  const [noticeVisible, setNoticeVisible] = useState(false);
  const [toast, setToast] = useState("");
  const [sensorTick, setSensorTick] = useState(0);
  const visibleDevices: AnyDevice[] = useMemo(
    () => [...devices, ...(simulation ? simDevices : [])],
    [devices, simDevices, simulation],
  );

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
        if (event.type === "device_state" && event.status) return { ...device, status: event.status };
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
      await api.sendCommand(device.id, {
        command: "set_power",
        parameters: { enabled: !onState(device) },
      });
      setToast("Command queued. Waiting for device state.");
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
      });
      setDevices((current) => [...current, created]);
      setAddVisible(false);
      setName("");
      setRoom("");
      setToast("Device registered.");
    } catch (error) {
      setToast(error instanceof ApiError ? error.message : "Unable to create device.");
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

  function sendNora() {
    const prompt = noraInput.trim();
    if (!prompt) return;
    const turnOn = prompt.toLowerCase().includes("on");
    const lights = simDevices.filter((device) => device.device_type.includes("light"));
    const actsLocally = simulation && prompt.toLowerCase().includes("light") && lights.length > 0;
    if (actsLocally) {
      setSimDevices((current) => current.map((device) => (
        lights.some((light) => light.id === device.id)
          ? { ...device, power: turnOn, status: turnOn ? "On" : "Off" }
          : device
      )));
    }
    setNoraMessages((current) => [
      ...current,
      { from: "you", text: prompt },
      {
        from: "nora",
        text: actsLocally
          ? `Local demo: ${lights.length} lights turned ${turnOn ? "on" : "off"}. No backend command was sent.`
          : "This is a local interface preview. Voice recognition and an AI provider are not connected.",
      },
    ]);
    setNoraInput("");
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
          {section === "automations" && <AutomationsScreen />}
          {section === "nora" && <NoraScreen messages={noraMessages} value={noraInput} onChange={setNoraInput} onSend={sendNora} />}
          {section === "settings" && <SettingsScreen apiStatus={apiStatus} socketStatus={socketStatus} simulation={simulation} onToggleSimulation={() => setSimulation((value) => !value)} />}
        </ScrollView>
        <View style={styles.bottomNav}>
          {navigation.map((item) => {
            const selected = item.id === section;
            return <Pressable key={item.id} onPress={() => setSection(item.id)} style={styles.navButton} accessibilityRole="button" accessibilityState={{ selected }} accessibilityLabel={item.label}>
              <Ionicons name={item.icon} size={19} color={selected ? "#087F95" : "#798794"} />
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
            <Text style={styles.formHint}>Creates a real device through the NEXORA API.</Text>
            <Pressable style={styles.primaryButton} onPress={() => void addDevice()}><Text style={styles.primaryButtonText}>Create device</Text></Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
      <Modal visible={noticeVisible} transparent animationType="slide" onRequestClose={() => setNoticeVisible(false)}>
        <View style={styles.noticeBackdrop}><View style={styles.noticeSheet}>
          <View style={styles.modalHead}><View><Text style={styles.modalTitle}>Notifications</Text><Text style={styles.mutedText}>In-app session alerts</Text></View><Pressable onPress={() => setNoticeVisible(false)}><Ionicons name="close" size={22} color={colors.ink} /></Pressable></View>
          {notifications.length ? notifications.slice(0, 6).map((item) => <View style={styles.notificationRow} key={item.id}><Ionicons name="notifications-outline" size={16} color="#11869B" /><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{item.title}</Text><Text style={styles.mutedText}>{item.detail}</Text></View></View>) : <Text style={styles.mutedText}>No new alerts. Push delivery is not configured.</Text>}
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
      return <Pressable key={room} style={styles.roomItem} onPress={() => onNavigate("devices")}><View style={styles.roomIcon}><Ionicons name="home-outline" size={17} color="#16869B" /></View><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{room}</Text><Text style={styles.mutedText}>{count} devices</Text></View><Ionicons name="chevron-forward" size={17} color="#9AA6AE" /></Pressable>;
    })}</View>
    <SectionHeader title="Live readings" action={socketStatus === "connected" ? "LIVE" : "WAITING"} />
    {sensors.length ? <View style={styles.panel}>{sensors.slice(0, 2).map((reading) => <View key={reading.name} style={styles.sensorItem}><Ionicons name="thermometer-outline" size={18} color="#4382C5" /><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{reading.name}</Text><Text style={styles.mutedText}>{reading.room}</Text></View><Text style={styles.sensorValue}>{reading.reading}{reading.unit}</Text></View>)}</View> : <EmptyCard text="Sensor history is not available through the current API." />}
    <Pressable style={styles.noraPromo} onPress={() => onNavigate("nora")}><View style={styles.noraPromoOrb}><Ionicons name="sparkles" size={19} color="#8BEEFB" /></View><View style={{ flex: 1 }}><Text style={styles.noraPromoTitle}>Meet NORA</Text><Text style={styles.noraPromoText}>Open the local assistant preview</Text></View><Ionicons name="arrow-forward" size={18} color="#D9F7FF" /></Pressable>
    <Pressable style={[styles.outlineButton, { marginTop: 10 }]} onPress={() => onNavigate("automations")}><Ionicons name="flash-outline" size={17} color="#087F95" /><Text style={styles.outlineButtonText}>Automation rules · preview</Text><Ionicons name="arrow-forward" size={15} color="#087F95" /></Pressable>
  </>;
}

function SectionHeader({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  return <View style={styles.sectionHeader}><Text style={styles.sectionTitle}>{title}</Text>{action && <Pressable onPress={onAction}><Text style={styles.sectionAction}>{action}</Text></Pressable>}</View>;
}

function DeviceTile({ device, onControl, onDelete }: { device: AnyDevice; onControl: () => void; onDelete?: () => void }) {
  const sensor = isSimulated(device) ? device.sensor_readings[0] : undefined;
  const actuator = /light|fan/i.test(device.device_type);
  const on = onState(device);
  return <View style={styles.deviceTile}>
    <View style={styles.tileTop}><View style={[styles.deviceGlyph, on && styles.deviceGlyphOn]}><Ionicons name={deviceIcon(device.device_type)} size={20} color={on ? "#087F95" : "#71818F"} /></View><View style={styles.tileActions}>{onDelete && !isSimulated(device) && <Pressable onPress={onDelete} accessibilityLabel={`Delete ${device.name}`}><Ionicons name="trash-outline" size={15} color="#87949E" /></Pressable>}<View style={[styles.onlineDot, { backgroundColor: device.online ? "#31B67B" : "#B8C1C8" }]} /></View></View>
    <Text style={styles.deviceName} numberOfLines={1}>{device.name}</Text><Text style={styles.deviceRoom} numberOfLines={1}>{device.room || "Unassigned"}{isSimulated(device) ? " · SIM" : ""}</Text>
    {sensor ? <View style={styles.sensorInline}><Text style={styles.sensorInlineValue}>{sensor.reading}{sensor.unit}</Text><Text style={styles.mutedText}>{sensor.name}</Text></View> : <Text style={styles.deviceState}>{device.online ? (on ? "Powered on" : "Powered off") : "Offline"}</Text>}
    {actuator && <Pressable style={[styles.controlButton, on && styles.controlButtonOn]} onPress={onControl}><Text style={[styles.controlText, on && styles.controlTextOn]}>{on ? "TURN OFF" : "TURN ON"}</Text><Ionicons name="power-outline" size={15} color={on ? "#07849A" : "#667085"} /></Pressable>}
  </View>;
}

function DevicesScreen({ devices, onControl, onAdd, onDelete }: { devices: AnyDevice[]; onControl: (device: AnyDevice) => void; onAdd: () => void; onDelete: (device: AnyDevice) => void }) {
  const rooms = [...new Set(devices.map((device) => device.room || "Unassigned"))];
  return <>
    <View style={styles.screenIntro}><Text style={styles.eyebrow}>DEVICE MANAGEMENT</Text><Text style={styles.screenTitle}>Your devices</Text><Text style={styles.mutedText}>Room-by-room controls · {devices.length} devices</Text></View>
    <Pressable style={styles.outlineButton} onPress={onAdd}><Ionicons name="add" size={18} color="#087F95" /><Text style={styles.outlineButtonText}>Register real device</Text></Pressable>
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
        return <View key={`${event.timestamp}-${index}`} style={styles.eventRow}><View style={styles.eventGlyph}><Ionicons name="pulse-outline" size={16} color="#13869A" /></View><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{event.type.replaceAll("_", " ")}</Text><Text style={styles.mutedText}>{device?.name ?? event.device_id ?? event.message ?? "Backend event"}{event.reading !== undefined ? ` · ${event.reading}${event.unit ?? ""}` : ""}</Text></View></View>;
      }) : <EmptyCard text="Simulator and WebSocket events will appear here." />}
    </View>
    <View style={[styles.panel, { marginTop: 14 }]}><View style={styles.cardHeadingRow}><Text style={styles.cardHeading}>Security center</Text><Ionicons name="shield-checkmark-outline" size={17} color="#218353" /></View><Text style={styles.mutedText}>The security-events model has no read endpoint yet. No live security status is available.</Text></View>
    <View style={[styles.panel, { marginTop: 14 }]}><Text style={styles.cardHeading}>Push notifications</Text><Text style={styles.mutedText}>In-app alert preview only. Push delivery is not configured.</Text></View>
  </>;
}

function AutomationsScreen() {
  return <>
    <View style={styles.screenIntro}><Text style={styles.eyebrow}>HOME ROUTINES</Text><Text style={styles.screenTitle}>Automations</Text><Text style={styles.mutedText}>Preview until the backend rules API is available.</Text></View>
    <View style={styles.automationHero}><Ionicons name="sparkles-outline" size={23} color="#77E5F4" /><Text style={styles.automationTitle}>Your home, in rhythm</Text><Text style={styles.automationBody}>NEXORA has an AutomationRule model, but there is no API or execution engine. These examples are visual only.</Text></View>
    {["Evening ambience · Sunset → living room lights", "Comfort airflow · Warm room → fan", "Away mode · Home empty → security"].map((rule) => <View key={rule} style={styles.ruleRow}><Ionicons name="flash-outline" size={17} color="#16869B" /><Text style={styles.ruleText}>{rule}</Text><View style={styles.disabledTrack}><View style={styles.disabledTrackInner} /></View></View>)}
  </>;
}

function NoraScreen({ messages, value, onChange, onSend }: { messages: { from: string; text: string }[]; value: string; onChange: (text: string) => void; onSend: () => void }) {
  return <>
    <View style={styles.noraHero}><View style={styles.noraHalo}><Ionicons name="sparkles" size={28} color="#9AF0FF" /></View><Text style={styles.eyebrowLight}>NEXORA HOME COMPANION</Text><Text style={styles.noraHeading}>Hello, I’m NORA.</Text><Text style={styles.heroText}>Assistant interface preview · local demo only</Text></View>
    <View style={[styles.panel, { marginTop: 14 }]}>
      <FlatList
        data={messages}
        keyExtractor={(_, index) => `nora-${index}`}
        scrollEnabled={false}
        renderItem={({ item }) => <View style={[styles.chatMessage, item.from === "you" && styles.chatUser]}><View style={styles.chatAvatar}><Text style={styles.chatAvatarText}>{item.from === "you" ? "P" : "N"}</Text></View><View style={styles.chatBubble}><Text style={styles.chatLabel}>{item.from === "you" ? "YOU" : "NORA · PREVIEW"}</Text><Text style={styles.chatText}>{item.text}</Text></View></View>}
      />
      <View style={styles.chatInputRow}><TextInput style={styles.chatInput} value={value} onChangeText={onChange} placeholder="Try: turn on the lights" placeholderTextColor="#9AA6AE" onSubmitEditing={onSend} /><Pressable style={styles.sendButton} onPress={onSend}><Ionicons name="arrow-up" size={18} color="white" /></Pressable></View>
      <Text style={styles.formHint}>Voice recognition and AI provider are not connected.</Text>
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
    <View style={styles.privacyNote}><Ionicons name="lock-closed-outline" size={15} color="#13869A" /><Text style={styles.mutedText}>Real-device controls use the existing API. The simulator never writes its sample devices to Neon.</Text></View>
  </>;
}

function SettingItem({ icon, title, detail, status }: { icon: keyof typeof Ionicons.glyphMap; title: string; detail: string; status: string }) {
  const connected = status === "connected";
  return <View style={styles.settingItem}><Ionicons name={icon} size={17} color="#13869A" /><View style={{ flex: 1 }}><Text style={styles.rowTitle}>{title}</Text><Text style={styles.mutedText}>{detail}</Text></View><Text style={[styles.settingStatus, connected ? styles.settingStatusOn : styles.settingStatusOff]}>{status}</Text></View>;
}

function EmptyCard({ text }: { text: string }) {
  return <View style={styles.emptyCard}><Ionicons name="information-circle-outline" size={20} color="#718899" /><Text style={styles.mutedText}>{text}</Text></View>;
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.charcoal },
  app: { flex: 1, backgroundColor: colors.paper },
  topbar: { minHeight: 58, paddingHorizontal: 16, flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: colors.charcoal },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 9 },
  brandGlyph: { width: 29, height: 29, borderRadius: 10, borderWidth: 1, borderColor: "#38BFD5", backgroundColor: "#142B38", alignItems: "center", justifyContent: "center" },
  brandGlyphInner: { width: 10, height: 10, borderWidth: 2, borderColor: "#7CEBFC", transform: [{ rotate: "45deg" }] },
  brand: { color: "white", fontWeight: "800", letterSpacing: 2, fontSize: 12 },
  brandCaption: { color: "#96AAB8", fontSize: 7, letterSpacing: 1.3, marginTop: 2 },
  topbarRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  connection: { flexDirection: "row", alignItems: "center", gap: 5, borderRadius: 14, paddingHorizontal: 8, paddingVertical: 6 },
  connectionOn: { backgroundColor: "#183A34" },
  connectionOff: { backgroundColor: "#343538" },
  statusDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#50D597" },
  connectionText: { color: "#E6F1F4", fontSize: 8, textTransform: "capitalize" },
  bellButton: { position: "relative", width: 33, height: 33, borderRadius: 11, backgroundColor: "white", alignItems: "center", justifyContent: "center" },
  bellCount: { position: "absolute", top: -3, right: -3, minWidth: 14, height: 14, borderRadius: 7, backgroundColor: "#079CB5", alignItems: "center", justifyContent: "center" },
  bellCountText: { color: "white", fontSize: 8, fontWeight: "700" },
  pageTitleBar: { paddingHorizontal: 17, paddingTop: 14, paddingBottom: 10, backgroundColor: colors.charcoal },
  pageKicker: { color: "#81A0B0", fontSize: 8, letterSpacing: 1.3, fontWeight: "700" },
  pageTitle: { color: "white", fontSize: 19, fontWeight: "700", marginTop: 4 },
  scrollContent: { paddingHorizontal: 15, paddingTop: 15, paddingBottom: 25 },
  heroCard: { overflow: "hidden", position: "relative", padding: 20, borderRadius: 19, backgroundColor: "#162633", borderWidth: 1, borderColor: "#253D4A" },
  heroGlow: { position: "absolute", width: 180, height: 180, borderRadius: 90, right: -70, top: -90, backgroundColor: "#164B60", opacity: 0.58 },
  eyebrowLight: { color: "#A2D7E0", fontSize: 8, letterSpacing: 1.3, fontWeight: "700" },
  heroTitle: { marginTop: 12, color: "white", fontSize: 26, lineHeight: 31, fontWeight: "700", letterSpacing: -0.6 },
  heroText: { marginTop: 7, color: "#B9C9D1", fontSize: 10, lineHeight: 16 },
  heroStats: { marginTop: 22, paddingTop: 14, borderTopWidth: 1, borderTopColor: "rgba(255,255,255,.12)", flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  heroStatValue: { color: "#F3FCFF", fontSize: 16, fontWeight: "700" },
  heroStatLabel: { marginTop: 4, color: "#93ACB8", fontSize: 7, letterSpacing: 0.7, fontWeight: "700" },
  statDivider: { height: 28, width: 1, backgroundColor: "rgba(255,255,255,.14)" },
  sectionHeader: { minHeight: 34, marginTop: 18, marginBottom: 8, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  sectionTitle: { color: colors.ink, fontSize: 14, fontWeight: "700", letterSpacing: -0.2 },
  sectionAction: { color: "#087F95", fontSize: 9, fontWeight: "700" },
  deviceGrid: { flexDirection: "row", flexWrap: "wrap", gap: 9 },
  deviceTile: { width: "48.5%", minHeight: 151, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  tileTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  deviceGlyph: { width: 34, height: 34, borderRadius: 11, backgroundColor: "#EFF3F5", alignItems: "center", justifyContent: "center" },
  deviceGlyphOn: { backgroundColor: "#E7F8FA" },
  onlineDot: { width: 7, height: 7, borderRadius: 4 },
  tileActions: { flexDirection: "row", alignItems: "center", gap: 8 },
  deviceName: { marginTop: 12, color: colors.ink, fontSize: 11, fontWeight: "700" },
  deviceRoom: { marginTop: 3, color: colors.mutedInk, fontSize: 8 },
  deviceState: { marginTop: 11, color: "#73818D", fontSize: 8 },
  controlButton: { marginTop: 8, height: 28, paddingHorizontal: 8, borderRadius: 8, borderWidth: 1, borderColor: "#E0E7EC", backgroundColor: "#F6F8FA", flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  controlButtonOn: { borderColor: "#B8E6EC", backgroundColor: "#EFFBFC" },
  controlText: { color: "#677582", fontSize: 8, fontWeight: "800", letterSpacing: 0.7 },
  controlTextOn: { color: "#087F95" },
  sensorInline: { marginTop: 7 },
  sensorInlineValue: { color: colors.ink, fontSize: 17, fontWeight: "700" },
  panel: { padding: 14, borderRadius: 15, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  roomItem: { flexDirection: "row", alignItems: "center", minHeight: 48, gap: 9, borderBottomWidth: 1, borderBottomColor: "#EDF1F4" },
  roomIcon: { width: 31, height: 31, borderRadius: 10, backgroundColor: "#EAF8FA", alignItems: "center", justifyContent: "center" },
  rowTitle: { color: colors.ink, fontSize: 10, fontWeight: "700" },
  mutedText: { color: "#7D8A95", fontSize: 8, lineHeight: 13, marginTop: 3 },
  sensorItem: { minHeight: 48, flexDirection: "row", alignItems: "center", gap: 10, borderBottomWidth: 1, borderBottomColor: "#EDF1F4" },
  sensorValue: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  noraPromo: { marginTop: 15, minHeight: 74, padding: 13, borderRadius: 15, backgroundColor: colors.charcoalSoft, flexDirection: "row", alignItems: "center", gap: 11 },
  noraPromoOrb: { width: 39, height: 39, borderRadius: 14, backgroundColor: "#1B4253", alignItems: "center", justifyContent: "center" },
  noraPromoTitle: { color: "white", fontSize: 12, fontWeight: "700" },
  noraPromoText: { color: "#AFC0CA", fontSize: 8, marginTop: 4 },
  bottomNav: { minHeight: 58, paddingHorizontal: 4, borderTopWidth: 1, borderTopColor: "#DCE5EA", backgroundColor: "white", flexDirection: "row", alignItems: "center", justifyContent: "space-around" },
  navButton: { flex: 1, alignItems: "center", justifyContent: "center", gap: 3, minHeight: 52 },
  navLabel: { color: "#798794", fontSize: 7 },
  navLabelActive: { color: "#087F95", fontWeight: "700" },
  screenIntro: { marginBottom: 9 },
  eyebrow: { color: "#778896", fontSize: 8, letterSpacing: 1.1, fontWeight: "700" },
  screenTitle: { marginTop: 5, marginBottom: 4, color: colors.ink, fontSize: 23, fontWeight: "700", letterSpacing: -0.5 },
  outlineButton: { height: 40, marginVertical: 8, borderRadius: 10, borderWidth: 1, borderColor: "#B9DEE5", backgroundColor: "white", flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7 },
  outlineButtonText: { color: "#087F95", fontSize: 10, fontWeight: "700" },
  cardHeading: { marginBottom: 10, color: colors.ink, fontSize: 13, fontWeight: "700" },
  cardHeadingRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  eventRow: { minHeight: 49, flexDirection: "row", alignItems: "center", gap: 9, borderBottomWidth: 1, borderBottomColor: "#EDF1F4" },
  eventGlyph: { width: 30, height: 30, borderRadius: 10, backgroundColor: "#EAF8FA", alignItems: "center", justifyContent: "center" },
  automationHero: { padding: 20, borderRadius: 17, backgroundColor: "#162633", borderWidth: 1, borderColor: "#253D4A" },
  automationTitle: { marginTop: 12, color: "white", fontSize: 19, fontWeight: "700" },
  automationBody: { marginTop: 7, color: "#B8C8D1", fontSize: 9, lineHeight: 15 },
  ruleRow: { minHeight: 58, marginTop: 10, paddingHorizontal: 12, borderRadius: 13, borderWidth: 1, borderColor: colors.border, backgroundColor: "white", flexDirection: "row", alignItems: "center", gap: 9 },
  ruleText: { flex: 1, color: "#344453", fontSize: 9 },
  disabledTrack: { width: 27, height: 15, padding: 2, borderRadius: 9, backgroundColor: "#D8DFE4" },
  disabledTrackInner: { width: 11, height: 11, borderRadius: 6, backgroundColor: "white" },
  noraHero: { alignItems: "center", padding: 21, borderRadius: 18, backgroundColor: "#162633" },
  noraHalo: { width: 62, height: 62, marginBottom: 13, borderRadius: 31, borderWidth: 1, borderColor: "#397387", backgroundColor: "#1A4050", alignItems: "center", justifyContent: "center" },
  noraHeading: { marginTop: 8, color: "white", fontSize: 22, fontWeight: "700" },
  chatMessage: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginVertical: 7 },
  chatUser: { flexDirection: "row-reverse" },
  chatAvatar: { width: 27, height: 27, borderRadius: 9, backgroundColor: "#E6F7F9", alignItems: "center", justifyContent: "center" },
  chatAvatarText: { color: "#087F95", fontSize: 10, fontWeight: "700" },
  chatBubble: { flex: 1, padding: 9, borderRadius: 11, backgroundColor: "#F5F8FA" },
  chatLabel: { color: "#8B98A2", fontSize: 7, fontWeight: "700", letterSpacing: 0.7 },
  chatText: { marginTop: 4, color: "#344453", fontSize: 9, lineHeight: 14 },
  chatInputRow: { flexDirection: "row", gap: 7, alignItems: "center", marginTop: 9, padding: 6, borderWidth: 1, borderColor: "#DCE6EC", borderRadius: 11, backgroundColor: "#FCFDFE" },
  chatInput: { flex: 1, minHeight: 35, paddingHorizontal: 8, color: colors.ink, fontSize: 9 },
  sendButton: { width: 33, height: 33, borderRadius: 10, backgroundColor: "#168AA2", alignItems: "center", justifyContent: "center" },
  formHint: { marginTop: 8, color: "#87939E", fontSize: 8 },
  settingItem: { minHeight: 53, flexDirection: "row", alignItems: "center", gap: 9, borderTopWidth: 1, borderTopColor: "#EDF1F4" },
  settingStatus: { textTransform: "capitalize", fontSize: 8, paddingHorizontal: 7, paddingVertical: 4, borderRadius: 6 },
  settingStatusOn: { color: "#218353", backgroundColor: "#EEF9F2" },
  settingStatusOff: { color: "#74818D", backgroundColor: "#F0F3F5" },
  settingToggle: { minHeight: 56, flexDirection: "row", alignItems: "center", gap: 10, borderTopWidth: 1, borderTopColor: "#EDF1F4" },
  switchTrack: { width: 34, height: 19, padding: 2, borderRadius: 10, backgroundColor: "#CBD4DB", justifyContent: "center" },
  switchTrackOn: { backgroundColor: "#14AFC2" },
  switchThumb: { width: 15, height: 15, borderRadius: 8, backgroundColor: "white" },
  switchThumbOn: { alignSelf: "flex-end" },
  previewText: { color: "#74818D", fontSize: 7, fontWeight: "700", letterSpacing: 0.5 },
  privacyNote: { flexDirection: "row", gap: 8, alignItems: "flex-start", marginTop: 14, padding: 12, borderRadius: 11, backgroundColor: "#E8F5F7" },
  emptyCard: { minHeight: 75, marginTop: 8, padding: 13, borderRadius: 13, borderWidth: 1, borderColor: colors.border, backgroundColor: "white", flexDirection: "row", gap: 8, alignItems: "center" },
  modalBackdrop: { flex: 1, padding: 18, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(10,20,29,.5)" },
  modal: { width: "100%", padding: 18, borderRadius: 17, backgroundColor: "white" },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 14 },
  modalTitle: { color: colors.ink, fontSize: 16, fontWeight: "700" },
  fieldLabel: { marginTop: 9, color: "#485867", fontSize: 9, fontWeight: "700" },
  input: { height: 40, marginTop: 5, paddingHorizontal: 10, borderWidth: 1, borderColor: "#DCE5EB", borderRadius: 9, color: colors.ink, backgroundColor: "#FBFDFE", fontSize: 10 },
  primaryButton: { height: 42, marginTop: 17, borderRadius: 10, backgroundColor: "#168AA2", alignItems: "center", justifyContent: "center" },
  primaryButtonText: { color: "white", fontSize: 10, fontWeight: "700" },
  noticeBackdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(10,20,29,.45)" },
  noticeSheet: { minHeight: 240, maxHeight: "70%", padding: 19, borderTopLeftRadius: 20, borderTopRightRadius: 20, backgroundColor: "white" },
  notificationRow: { minHeight: 48, flexDirection: "row", alignItems: "center", gap: 9, borderTopWidth: 1, borderTopColor: "#EDF1F4" },
  toast: { position: "absolute", bottom: 72, left: 15, right: 15, padding: 12, borderRadius: 10, backgroundColor: "#152633", elevation: 5 },
  toastText: { color: "white", fontSize: 10 },
});

export default App;
