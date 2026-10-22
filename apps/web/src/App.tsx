import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity,
  ArrowUpRight,
  Bell,
  Bot,
  ChevronDown,
  CircleHelp,
  Command,
  Fan,
  Home,
  Lightbulb,
  LoaderCircle,
  LockKeyhole,
  Mic,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Settings,
  Shield,
  Sparkles,
  Thermometer,
  Trash2,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import {
  ApiError,
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

type Section = "overview" | "devices" | "activity" | "automations" | "nora" | "settings";
type Connection = "checking" | "connected" | "offline";
type AnyDevice = Device | SimulatedDevice;

const apiBase = import.meta.env.VITE_API_URL ?? "";
const api = new NexoraApi(apiBase);

const navItems: { id: Section; label: string; icon: typeof Home }[] = [
  { id: "overview", label: "Overview", icon: Home },
  { id: "devices", label: "Devices", icon: Radio },
  { id: "activity", label: "Activity & safety", icon: Activity },
  { id: "automations", label: "Automations", icon: Sparkles },
  { id: "nora", label: "NORA assistant", icon: Bot },
  { id: "settings", label: "Settings", icon: Settings },
];

function isSimulated(device: AnyDevice): device is SimulatedDevice {
  return "simulated" in device && device.simulated;
}

function deviceIsOn(device: AnyDevice): boolean {
  return isSimulated(device)
    ? device.power
    : device.status.toLowerCase() === "on" || device.status.toLowerCase() === "active";
}

function iconFor(device: AnyDevice) {
  const kind = device.device_type.toLowerCase();
  if (kind.includes("fan")) return Fan;
  if (kind.includes("sensor") || kind.includes("temperature")) return Thermometer;
  return Lightbulb;
}

function formatTime(value?: string): string {
  if (!value) return "Just now";
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function App() {
  const [section, setSection] = useState<Section>("overview");
  const [devices, setDevices] = useState<Device[]>([]);
  const [simDevices, setSimDevices] = useState<SimulatedDevice[]>(createDemoDevices);
  const [simulation, setSimulation] = useState(true);
  const [apiConnection, setApiConnection] = useState<Connection>("checking");
  const [wsConnection, setWsConnection] = useState<Connection>("checking");
  const mqttConnection = "unknown" as const;
  const [events, setEvents] = useState<DeviceEvent[]>([]);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [notifications, setNotifications] = useState<ActivityItem[]>([]);
  const [toast, setToast] = useState("");
  const [query, setQuery] = useState("");
  const [showAddDevice, setShowAddDevice] = useState(false);
  const [assistantText, setAssistantText] = useState("");
  const [assistantMessages, setAssistantMessages] = useState([
    {
      from: "nora",
      text: "Hi, I’m NORA. This is the local assistant preview. Try “turn on the lights” while simulation is on.",
    },
  ]);
  const tickRef = useRef(0);
  const apiDevices = useMemo(
    () => devices.filter((device) => device.name.toLowerCase().includes(query.toLowerCase())),
    [devices, query],
  );
  const allDevices: AnyDevice[] = useMemo(
    () => [...apiDevices, ...(simulation ? simDevices : [])],
    [apiDevices, simDevices, simulation],
  );
  const onlineCount = allDevices.filter((device) => device.online).length;

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const [, currentDevices] = await Promise.all([api.health(), api.listDevices()]);
        if (!alive) return;
        setApiConnection("connected");
        setDevices(currentDevices);
      } catch {
        if (alive) setApiConnection("offline");
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let retryTimer = 0;
    let closed = false;
    const connect = () => {
      if (closed) return;
      try {
        socket = new WebSocket(websocketUrl(apiBase, window.location.href));
        socket.onopen = () => setWsConnection("connected");
        socket.onmessage = (message) => {
          try {
            const event: unknown = JSON.parse(String(message.data));
            if (!isDeviceEvent(event)) return;
            handleDeviceEvent(event, setDevices, setEvents, setNotifications);
          } catch {
            // Ignore non-JSON echo messages from the existing WebSocket endpoint.
          }
        };
        socket.onerror = () => setWsConnection("offline");
        socket.onclose = () => {
          setWsConnection("offline");
          if (!closed) retryTimer = window.setTimeout(connect, 2500);
        };
      } catch {
        setWsConnection("offline");
        retryTimer = window.setTimeout(connect, 2500);
      }
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  useEffect(() => {
    if (!simulation) return;
    const timer = window.setInterval(() => {
      const tick = ++tickRef.current;
      const result = tickSimulatedSensors(simDevices, tick);
      setSimDevices(result.devices);
      setEvents((current) => [...result.events, ...current].slice(0, 100));
    }, 3500);
    return () => window.clearInterval(timer);
  }, [simulation, simDevices]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function addActivity(title: string, detail: string, kind: ActivityItem["kind"] = "device") {
    setNotifications((current) => [
      {
        id: `${Date.now()}-${Math.random()}`,
        title,
        detail,
        timestamp: new Date().toISOString(),
        kind,
      },
      ...current,
    ].slice(0, 20));
  }

  async function controlDevice(device: AnyDevice) {
    if (isSimulated(device)) {
      const result = toggleSimulatedDevice(device);
      setSimDevices((current) => current.map((item) => item.id === device.id ? result.device : item));
      setEvents((current) => [result.event, ...current].slice(0, 100));
      addActivity(`${device.name} ${result.device.power ? "turned on" : "turned off"}`, `${device.room} · local simulation`);
      return;
    }
    try {
      await api.sendCommand(device.id, {
        command: "set_power",
        parameters: { enabled: !deviceIsOn(device) },
      });
      setToast("Command queued. Waiting for a device update.");
    } catch (error) {
      setToast(error instanceof ApiError ? error.message : "Could not send device command.");
    }
  }

  async function createDevice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const created = await api.createDevice({
        name: String(form.get("name")).trim(),
        room: String(form.get("room")).trim() || null,
        device_type: String(form.get("device_type")).trim(),
      });
      setDevices((current) => [...current, created]);
      setShowAddDevice(false);
      setToast("Device registered.");
      addActivity(`${created.name} registered`, created.room ?? "No room assigned");
    } catch (error) {
      setToast(error instanceof ApiError ? error.message : "Could not create device.");
    }
  }

  function handleDeviceEvent(
    event: DeviceEvent,
    updateDevices: typeof setDevices,
    updateEvents: typeof setEvents,
    updateNotifications: typeof setNotifications,
  ) {
    updateEvents((current) => [event, ...current].slice(0, 100));
    if (event.device_id) {
      updateDevices((current) => current.map((device) => {
        if (device.id !== event.device_id) return device;
        if (event.type === "device_state" && event.status) return { ...device, status: event.status };
        if (event.type === "device_availability" && typeof event.online === "boolean") {
          return { ...device, online: event.online };
        }
        return device;
      }));
    }
    const title = event.type.replaceAll("_", " ");
    const detail = event.device_id ? `Device ${event.device_id}` : event.message ?? "Backend event";
    const kind: ActivityItem["kind"] = event.type === "device_sensor" || event.type === "simulator_sensor"
      ? "sensor"
      : event.type === "system_event"
        ? "system"
        : "device";
    updateNotifications((current) => [{
      id: `${Date.now()}-${Math.random()}`,
      title,
      detail,
      timestamp: event.timestamp ?? new Date().toISOString(),
      kind,
    }, ...current].slice(0, 20));
  }

  function sendNoraMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = assistantText.trim();
    if (!prompt) return;
    const lowered = prompt.toLowerCase();
    const turnOn = lowered.includes("on");
    const targetLights = simDevices.filter((device) => device.device_type.includes("light"));
    const shouldControlLights = lowered.includes("light") && targetLights.length > 0 && simulation;
    if (shouldControlLights) {
      setSimDevices((current) => current.map((device) => (
        targetLights.some((target) => target.id === device.id)
          ? { ...device, power: turnOn, status: turnOn ? "On" : "Off" }
          : device
      )));
    }
    const response = shouldControlLights
      ? `Local simulation: ${targetLights.length} lights turned ${turnOn ? "on" : "off"}. This did not send a command to the backend.`
      : "I’m in interface-preview mode. Live voice recognition and AI actions are not connected yet.";
    setAssistantMessages((current) => [
      ...current,
      { from: "you", text: prompt },
      { from: "nora", text: response },
    ]);
    setAssistantText("");
  }

  const pageTitle = navItems.find((item) => item.id === section)?.label ?? "Overview";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={() => setSection("overview")} aria-label="NEXORA home">
          <span className="brand-mark"><span /></span>
          <span>NEXORA<small>HOME INTELLIGENCE</small></span>
        </a>
        <div className="home-switcher">
          <div className="home-avatar"><Home size={17} /></div>
          <div><strong>Prince's residence</strong><span>Home profile</span></div>
          <ChevronDown size={15} />
        </div>
        <nav aria-label="Main navigation" className="main-nav">
          <span className="nav-caption">WORKSPACE</span>
          {navItems.map(({ id, label, icon: Icon }) => (
            <button
              className={`nav-item ${section === id ? "selected" : ""}`}
              key={id}
              onClick={() => setSection(id)}
              type="button"
            >
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
              {id === "nora" && <span className="nav-pulse" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="security-note"><Shield size={16} /><span>Local-first controls<br /><strong>Your home, your data</strong></span></div>
          <button className="profile-button" type="button" onClick={() => setSection("settings")}>
            <span className="profile-avatar">P</span><span><strong>Home owner</strong><small>Personal space</small></span>
            <Settings size={16} />
          </button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><span className="crumb-divider">/</span><strong>{pageTitle}</strong></div>
          <div className="top-actions">
            <div className={`connection-chip ${apiConnection}`}>
              {apiConnection === "connected" ? <Wifi size={14} /> : apiConnection === "checking" ? <LoaderCircle size={14} className="spin" /> : <WifiOff size={14} />}
              <span>API {apiConnection}</span>
            </div>
            <div className={`connection-chip ${wsConnection}`}>
              <span className="tiny-dot" /><span>Live {wsConnection}</span>
            </div>
            <button
              className={`simulation-chip ${simulation ? "active" : ""}`}
              type="button"
              aria-pressed={simulation}
              onClick={() => setSimulation((value) => !value)}
            >
              <span className="tiny-dot" /> Simulator {simulation ? "on" : "off"}
            </button>
            <button className="icon-button notification-trigger" type="button" aria-label="Open notifications" onClick={() => setNoticeOpen((value) => !value)}>
              <Bell size={18} />{notifications.length > 0 && <i>{notifications.length > 9 ? "9+" : notifications.length}</i>}
            </button>
          </div>
        </header>

        {noticeOpen && (
          <section className="notification-popover" aria-label="Notifications">
            <div className="popover-heading"><div><strong>Notifications</strong><span>Local session alerts</span></div><button className="icon-button small" onClick={() => setNoticeOpen(false)} aria-label="Close notifications"><X size={16} /></button></div>
            {notifications.length ? notifications.slice(0, 5).map((item) => <div className="notification-row" key={item.id}><span className="notification-mark"><Bell size={14} /></span><div><strong>{item.title}</strong><p>{item.detail}</p></div><time>{formatTime(item.timestamp)}</time></div>) : <p className="empty-note">No new alerts. Push delivery is not configured by the backend.</p>}
          </section>
        )}

        <div className="page-wrap">
          {section === "overview" && (
            <OverviewPage
              devices={allDevices}
              simulation={simulation}
              onlineCount={onlineCount}
              apiConnection={apiConnection}
              wsConnection={wsConnection}
              events={events}
              onControl={controlDevice}
              onNavigate={setSection}
              onNora={() => setSection("nora")}
            />
          )}
          {section === "devices" && (
            <DevicesPage
              devices={allDevices}
              query={query}
              onQuery={setQuery}
              onControl={controlDevice}
              onAdd={() => setShowAddDevice(true)}
              onDelete={(device) => {
                if (!isSimulated(device) && window.confirm(`Delete ${device.name}?`)) {
                  void api.deleteDevice(device.id).then(() => {
                    setDevices((current) => current.filter((item) => item.id !== device.id));
                    setToast(`${device.name} deleted.`);
                  }).catch((error: unknown) => {
                    setToast(error instanceof ApiError ? error.message : "Could not delete device.");
                  });
                }
              }}
            />
          )}
          {section === "activity" && <ActivityPage devices={allDevices} events={events} />}
          {section === "automations" && <AutomationPage />}
          {section === "nora" && (
            <NoraPage
              messages={assistantMessages}
              text={assistantText}
              onText={setAssistantText}
              onSubmit={sendNoraMessage}
              onMic={() => setToast("Voice recognition is a UI preview and is not connected yet.")}
            />
          )}
          {section === "settings" && (
            <SettingsPage
              apiBase={apiBase || "Same-origin development proxy"}
              apiConnection={apiConnection}
              wsConnection={wsConnection}
              mqttConnection={mqttConnection}
              simulation={simulation}
              onToggleSimulation={() => setSimulation((value) => !value)}
              onRefresh={() => window.location.reload()}
            />
          )}
        </div>
      </main>

      {showAddDevice && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setShowAddDevice(false);
        }}>
          <form className="modal-card" onSubmit={createDevice}>
            <div className="modal-title"><div><span className="eyebrow">DEVICE MANAGEMENT</span><h2>Register a device</h2></div><button className="icon-button" type="button" aria-label="Close" onClick={() => setShowAddDevice(false)}><X size={18} /></button></div>
            <label>Device name<input name="name" placeholder="e.g. Hallway light" required maxLength={200} /></label>
            <label>Room<input name="room" placeholder="e.g. Hallway" maxLength={120} /></label>
            <label>Device type<input name="device_type" placeholder="e.g. smart_light" required maxLength={100} /></label>
            <p className="form-hint">This registers a real backend device. Demo simulator devices are local-only.</p>
            <div className="modal-actions"><button className="button secondary" type="button" onClick={() => setShowAddDevice(false)}>Cancel</button><button className="button primary" type="submit"><Plus size={16} />Create device</button></div>
          </form>
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

function OverviewPage(props: {
  devices: AnyDevice[];
  simulation: boolean;
  onlineCount: number;
  apiConnection: Connection;
  wsConnection: Connection;
  events: DeviceEvent[];
  onControl: (device: AnyDevice) => void;
  onNavigate: (section: Section) => void;
  onNora: () => void;
}) {
  const rooms = [...new Set(props.devices.map((device) => device.room || "Unassigned"))];
  const simulatedSensors = props.devices.filter((device): device is SimulatedDevice => isSimulated(device))
    .flatMap((device) => device.sensor_readings.map((reading) => ({ ...reading, room: device.room })));
  const liveSensors = props.events
    .filter((event) => event.type === "device_sensor")
    .map((event) => ({
      name: event.name ?? event.sensor_type ?? "Sensor",
      sensor_type: event.sensor_type ?? "sensor",
      reading: event.reading ?? null,
      unit: event.unit ?? null,
      timestamp: event.timestamp ?? new Date().toISOString(),
      room: props.devices.find((device) => device.id === event.device_id)?.room ?? "Home",
    }));
  const sensors = [...liveSensors, ...simulatedSensors];
  const quickControls = props.devices.filter((device) => /light|fan/i.test(device.device_type)).slice(0, 4);
  return (
    <>
      <section className="welcome-row">
        <div><span className="eyebrow"><span className="eyebrow-light" /> YOUR HOME, IN SYNC</span><h1>Good evening, <em>Prince</em></h1><p>A calmer, smarter home starts here.</p></div>
        <div className="date-card"><span className="date-icon"><Sparkles size={16} /></span><div><strong>{new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" }).format(new Date())}</strong><span>Home overview</span></div></div>
      </section>
      <section className="metrics-grid" aria-label="Home summary">
        <MetricCard icon={Radio} label="Devices online" value={`${props.onlineCount}/${props.devices.length}`} detail="Across your home" />
        <MetricCard icon={Home} label="Active rooms" value={String(rooms.length)} detail="Rooms with devices" />
        <MetricCard icon={Thermometer} label="Home temperature" value={sensors.find((sensor) => sensor.sensor_type === "temperature")?.reading !== undefined ? `${sensors.find((sensor) => sensor.sensor_type === "temperature")?.reading}°` : "—"} detail={props.simulation ? "Simulated live reading" : "Awaiting sensor feed"} />
        <MetricCard icon={Shield} label="Home security" value="Protected" detail="No active alerts" positive />
      </section>
      <section className="content-grid overview-grid">
        <div className="panel quick-panel">
          <div className="panel-heading"><div><span className="eyebrow">AT A GLANCE</span><h2>Quick controls</h2></div><button className="text-link" onClick={() => props.onNavigate("devices")}>All devices <ArrowUpRight size={15} /></button></div>
          <div className="quick-controls">
            {quickControls.map((device) => <DeviceCard key={device.id} device={device} compact onControl={() => props.onControl(device)} />)}
            {!quickControls.length && <EmptyState title="No quick controls yet" detail="Add a device or enable the local simulator." />}
          </div>
        </div>
        <div className="panel nora-feature">
          <div className="nora-orb"><span /><i /><b /></div>
          <span className="eyebrow">YOUR HOME COMPANION</span><h2>Meet NORA</h2>
          <p>A voice assistant interface preview, ready for future integrations.</p>
          <button className="button light-button" onClick={props.onNora}><Mic size={16} />Open NORA <ArrowUpRight size={15} /></button>
          <small><span className="tiny-dot" /> Preview mode · no AI service connected</small>
        </div>
        <div className="panel rooms-panel">
          <div className="panel-heading"><div><span className="eyebrow">YOUR SPACE</span><h2>Rooms</h2></div><span className="subtle-count">{rooms.length} areas</span></div>
          <div className="room-list">
            {rooms.map((room) => {
              const roomDevices = props.devices.filter((device) => (device.room || "Unassigned") === room);
              return <button className="room-row" key={room} onClick={() => props.onNavigate("devices")}><span className="room-icon"><Home size={17} /></span><span className="room-label"><strong>{room}</strong><small>{roomDevices.length} devices · {roomDevices.filter((device) => device.online).length} online</small></span><span className="room-mini-icons">{roomDevices.slice(0, 3).map((device) => { const Icon = iconFor(device); return <i key={device.id}><Icon size={13} /></i>; })}</span><ArrowUpRight size={15} /></button>;
            })}
          </div>
        </div>
        <div className="panel sensor-panel">
          <div className="panel-heading"><div><span className="eyebrow">ENVIRONMENT</span><h2>Live readings</h2></div><span className={`live-tag ${props.wsConnection === "connected" ? "live" : ""}`}><i />{props.wsConnection === "connected" ? "LIVE" : "WAITING"}</span></div>
          {sensors.length ? <div className="sensor-list">{sensors.slice(0, 3).map((sensor) => <div className="sensor-row" key={`${sensor.room}-${sensor.name}`}><span className="sensor-icon"><Thermometer size={17} /></span><div><strong>{sensor.name}</strong><small>{sensor.room ?? "Home"} · {formatTime(sensor.timestamp)}</small></div><b>{sensor.reading}{sensor.unit}</b></div>)}</div> : <EmptyState title="No readings received" detail="Sensor history is not exposed by the current API." />}
          <button className="text-link bottom-link" onClick={() => props.onNavigate("activity")}>View activity <ArrowUpRight size={15} /></button>
        </div>
      </section>
      <section className="panel connection-banner">
        <span className="banner-orb"><Wifi size={18} /></span><div><strong>Everything in one place</strong><span>API {props.apiConnection} · WebSocket {props.wsConnection} · simulator {props.simulation ? "active locally" : "off"}</span></div><button className="button secondary" onClick={() => props.onNavigate("settings")}><Settings size={15} />Connectivity</button>
      </section>
    </>
  );
}

function MetricCard({ icon: Icon, label, value, detail, positive = false }: {
  icon: typeof Home; label: string; value: string; detail: string; positive?: boolean;
}) {
  return <article className="metric-card"><div className="metric-top"><span className="metric-icon"><Icon size={18} /></span><span className="metric-spark"><span /><span /><span /><span /></span></div><span className="metric-label">{label}</span><strong className={positive ? "positive-value" : ""}>{value}</strong><small>{detail}</small></article>;
}

function DeviceCard({ device, compact = false, onControl, onDelete }: {
  device: AnyDevice; compact?: boolean; onControl: () => void; onDelete?: () => void;
}) {
  const Icon = iconFor(device);
  const sensor = isSimulated(device) ? device.sensor_readings[0] : undefined;
  const isActuator = /light|fan/i.test(device.device_type);
  return (
    <article className={`device-card ${compact ? "compact" : ""} ${deviceIsOn(device) ? "is-on" : ""}`}>
      <div className="device-card-top"><span className={`device-icon ${device.device_type.includes("fan") ? "fan-icon" : ""}`}><Icon size={19} /></span><div className="device-card-tools"><span className={`device-status ${device.online ? "online" : "offline"}`}><i />{device.online ? "Online" : "Offline"}</span>{onDelete && !isSimulated(device) && <button type="button" className="device-delete" aria-label={`Delete ${device.name}`} onClick={onDelete}><Trash2 size={13} /></button>}</div></div>
      <div className="device-card-title"><strong>{device.name}</strong><span>{device.room || "Unassigned"}{isSimulated(device) && <em> · SIM</em>}</span></div>
      {sensor ? <div className="device-sensor-value">{sensor.reading}{sensor.unit}<small>{sensor.name}</small></div> : <div className="device-state-line"><span className={`power-indicator ${deviceIsOn(device) ? "powered" : ""}`} />{deviceIsOn(device) ? "Powered on" : "Powered off"}</div>}
      {isActuator && <button className={`device-toggle ${deviceIsOn(device) ? "on" : ""}`} type="button" onClick={onControl} aria-label={`${deviceIsOn(device) ? "Turn off" : "Turn on"} ${device.name}`}><span /><b>{deviceIsOn(device) ? "ON" : "OFF"}</b></button>}
    </article>
  );
}

function DevicesPage(props: {
  devices: AnyDevice[];
  query: string;
  onQuery: (value: string) => void;
  onControl: (device: AnyDevice) => void;
  onAdd: () => void;
  onDelete: (device: AnyDevice) => void;
}) {
  const rooms = [...new Set(props.devices.map((device) => device.room || "Unassigned"))];
  return <>
    <PageHeading eyebrow="HOME DIRECTORY" title="Your devices" description="Manage connected and simulated devices room by room." action={<button className="button primary" onClick={props.onAdd}><Plus size={16} />Add device</button>} />
    <div className="toolbar"><div className="search-field"><Search size={17} /><input value={props.query} onChange={(event) => props.onQuery(event.target.value)} placeholder="Search devices" aria-label="Search devices" /></div><span className="subtle-count">{props.devices.length} devices</span></div>
    {rooms.map((room) => {
      const devices = props.devices.filter((device) => (device.room || "Unassigned") === room);
      return <section className="room-section" key={room}><div className="room-section-heading"><div className="room-icon"><Home size={17} /></div><div><h2>{room}</h2><span>{devices.length} devices</span></div><span className="room-line" /></div><div className="device-grid">{devices.map((device) => <DeviceCard key={device.id} device={device} onControl={() => props.onControl(device)} onDelete={() => props.onDelete(device)} />)}</div></section>;
    })}
    {!props.devices.length && <EmptyState title="No devices match" detail="Check the search or register a device through the existing API." />}
  </>;
}

function ActivityPage({ devices, events }: { devices: AnyDevice[]; events: DeviceEvent[] }) {
  const activity = events.slice(0, 25);
  return <>
    <PageHeading eyebrow="REAL-TIME FEED" title="Activity & safety" description="Live events from this session and device connectivity." />
    <div className="content-grid two-column">
      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">LIVE SESSION</span><h2>Recent activity</h2></div><span className="subtle-count">{activity.length} events</span></div>
        {activity.length ? <div className="timeline">{activity.map((event, index) => {
          const device = devices.find((item) => item.id === event.device_id);
          return <div className="timeline-item" key={`${event.timestamp}-${index}`}><span className="timeline-icon"><Activity size={15} /></span><div><strong>{event.type.replaceAll("_", " ")}</strong><p>{device?.name ?? event.device_id ?? event.message ?? "Backend event"}{event.status ? ` · ${event.status}` : ""}{event.reading !== undefined ? ` · ${event.reading}${event.unit ?? ""}` : ""}</p></div><time>{formatTime(event.timestamp)}</time></div>;
        })}</div> : <EmptyState title="No recent events" detail="Simulator actions and incoming WebSocket events appear here." />}
      </section>
      <section className="panel safety-panel">
        <div className="panel-heading"><div><span className="eyebrow">SAFETY CENTER</span><h2>Security events</h2></div><span className="status-pill calm"><Shield size={13} />Clear</span></div>
        <div className="security-empty"><span><LockKeyhole size={21} /></span><strong>Security event API not available</strong><p>The backend has a security-events model, but no read endpoint yet. Nothing here is represented as live security status.</p></div>
        <div className="security-foot"><CircleHelp size={14} /> Security history needs a backend endpoint.</div>
      </section>
      <section className="panel notification-preview">
        <div className="panel-heading"><div><span className="eyebrow">ALERTS</span><h2>Notification center</h2></div><Bell size={17} /></div>
        <div className="notification-preview-body"><span className="notification-badge"><Bell size={16} /></span><div><strong>In-app notification preview</strong><p>Live session events can appear in the notification tray. Mobile/browser push delivery is not configured.</p></div></div>
      </section>
    </div>
  </>;
}

function AutomationPage() {
  return <>
    <PageHeading eyebrow="HOME ROUTINES" title="Automations" description="A consistent place for schedules and intelligent routines." action={<button className="button secondary" disabled><Plus size={16} />Create rule</button>} />
    <section className="automation-banner"><div className="automation-orb"><Sparkles size={23} /></div><div><span className="eyebrow">AUTOMATION BUILDER</span><h2>Make your home work in sync</h2><p>The backend has an AutomationRule model, but no rules API or execution engine. These controls are a design preview and do not create or run rules.</p></div><span className="preview-label">PREVIEW</span></section>
    <div className="automation-preview-grid">
      <article className="automation-preview-card"><span className="automation-icon"><Lightbulb size={18} /></span><div><strong>Evening ambience</strong><small>Sunset · Living room lights</small></div><span className="disabled-switch" /></article>
      <article className="automation-preview-card"><span className="automation-icon blue"><Fan size={18} /></span><div><strong>Comfort airflow</strong><small>Temperature above 25°C · Fan</small></div><span className="disabled-switch" /></article>
      <article className="automation-preview-card"><span className="automation-icon orange"><Shield size={18} /></span><div><strong>Away mode</strong><small>When home is empty · Security</small></div><span className="disabled-switch" /></article>
    </div>
  </>;
}

function NoraPage(props: {
  messages: { from: string; text: string }[];
  text: string;
  onText: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onMic: () => void;
}) {
  return <div className="nora-page">
    <section className="nora-hero"><div className="nora-orb large"><span /><i /><b /></div><span className="eyebrow">NEXORA ORCHESTRATION & RESPONSE ASSISTANT</span><h1>Meet <em>NORA</em></h1><p>Your home’s intelligent companion—designed to make everyday control feel effortless.</p><span className="preview-label">INTERFACE PREVIEW</span></section>
    <section className="panel nora-chat">
      <div className="panel-heading"><div><span className="eyebrow">CONVERSATION</span><h2>Home assistant</h2></div><span className="status-pill neutral"><span className="tiny-dot" />Preview mode</span></div>
      <div className="chat-log">{props.messages.map((message, index) => <div className={`chat-message ${message.from === "you" ? "from-user" : ""}`} key={`${index}-${message.from}`}><span className="chat-avatar">{message.from === "you" ? "P" : <Sparkles size={15} />}</span><div><small>{message.from === "you" ? "YOU" : "NORA · LOCAL PREVIEW"}</small><p>{message.text}</p></div></div>)}</div>
      <form className="chat-input" onSubmit={props.onSubmit}><button type="button" className="icon-button mic-button" onClick={props.onMic} aria-label="Voice input preview"><Mic size={18} /></button><input value={props.text} onChange={(event) => props.onText(event.target.value)} placeholder="Ask NORA to control your simulated home…" aria-label="Message NORA" /><button className="button primary" type="submit">Send <ArrowUpRight size={15} /></button></form>
      <div className="chat-foot"><span><LockKeyhole size={13} /> Local UI demo · no AI service or voice recognition</span><span>Try: “turn on the lights”</span></div>
    </section>
  </div>;
}

function SettingsPage(props: {
  apiBase: string;
  apiConnection: Connection;
  wsConnection: Connection;
  mqttConnection: "disabled" | "unknown";
  simulation: boolean;
  onToggleSimulation: () => void;
  onRefresh: () => void;
}) {
  return <>
    <PageHeading eyebrow="PREFERENCES" title="Settings & connectivity" description="Connection health and local development options." action={<button className="button secondary" onClick={props.onRefresh}><RefreshCw size={15} />Refresh</button>} />
    <div className="settings-grid">
      <section className="panel settings-panel"><div className="panel-heading"><div><span className="eyebrow">BACKEND</span><h2>Service connections</h2></div><Wifi size={18} /></div>
        <SettingRow icon={Radio} title="FastAPI" detail={props.apiBase} status={props.apiConnection} />
        <SettingRow icon={Activity} title="WebSocket" detail="Live device events · /ws" status={props.wsConnection} />
        <SettingRow icon={Command} title="MQTT broker" detail="Broker availability is not exposed by the current API" status={props.mqttConnection} />
        <p className="settings-note">Commands to real devices require MQTT to be explicitly enabled and a broker connected. This UI does not enable MQTT.</p>
      </section>
      <section className="panel settings-panel"><div className="panel-heading"><div><span className="eyebrow">DEVELOPMENT</span><h2>Local simulator</h2></div><Sparkles size={18} /></div>
        <div className="setting-toggle-row"><div><strong>Simulated devices</strong><span>In-memory only · never written to the backend</span></div><button className={`switch-control ${props.simulation ? "enabled" : ""}`} onClick={props.onToggleSimulation} type="button" aria-label="Toggle simulated devices" aria-pressed={props.simulation}><i /></button></div>
        <div className="setting-toggle-row"><div><strong>Notifications</strong><span>In-app preview only · push service not configured</span></div><span className="status-pill neutral">Preview</span></div>
        <div className="setting-toggle-row"><div><strong>Data & privacy</strong><span>Real device changes use the connected NEXORA API.</span></div><LockKeyhole size={16} /></div>
      </section>
    </div>
  </>;
}

function SettingRow({ icon: Icon, title, detail, status }: {
  icon: typeof Home; title: string; detail: string; status: Connection | "unknown" | "disabled";
}) {
  const connected = status === "connected";
  return <div className="setting-row"><span className="setting-icon"><Icon size={16} /></span><div><strong>{title}</strong><small>{detail}</small></div><span className={`status-pill ${connected ? "positive" : status === "offline" ? "negative" : "neutral"}`}><i />{status}</span></div>;
}

function PageHeading({ eyebrow, title, description, action }: {
  eyebrow: string; title: string; description: string; action?: ReactNode;
}) {
  return <section className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</section>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><span><CircleHelp size={19} /></span><strong>{title}</strong><p>{detail}</p></div>;
}

export default App;
