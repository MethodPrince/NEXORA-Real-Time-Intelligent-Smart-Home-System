const isDevelopment = process.env.APP_VARIANT === "development";

module.exports = ({ config }) => {
  const infoPlist = config.ios && config.ios.infoPlist
    ? config.ios.infoPlist
    : {};

  return {
    ...config,
    android: {
      ...config.android,
      ...(isDevelopment ? { usesCleartextTraffic: true } : {}),
    },
    ios: {
      ...config.ios,
      ...(isDevelopment
        ? {
            infoPlist: {
              ...infoPlist,
              NSLocalNetworkUsageDescription:
                "Connect to your NEXORA backend on your local network.",
              NSAppTransportSecurity: {
                ...infoPlist.NSAppTransportSecurity,
                NSAllowsArbitraryLoadsInLocalNetworking: true,
              },
            },
          }
        : {}),
    },
  };
};
