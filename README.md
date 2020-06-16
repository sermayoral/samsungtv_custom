[![](https://img.shields.io/github/release/sermayoral/ha-samsungtv-encrypted/all.svg?style=for-the-badge)](https://github.com/sermayoral/ha-samsungtv-encrypted/releases)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![](https://img.shields.io/github/license/sermayoral/ha-samsungtv-encrypted?style=for-the-badge)](LICENSE)
[![](https://img.shields.io/badge/MAINTAINER-%40sermayoral-red?style=for-the-badge)](https://github.com/sermayoral)
[![](https://img.shields.io/badge/COMMUNITY-FORUM-success?style=for-the-badge)](https://community.home-assistant.io)

# HomeAssistant - SamsungTV Encrypted Component

This is a custom component to allow control of Encrypted SamsungTV devices in [HomeAssistant](https://home-assistant.io). 
This should work on H and J 2014/2015 models (according to [PySmartCrypto](https://github.com/eclair4151/SmartCrypto)
specs). Is a modified version of the built-in [samsungtv](https://www.home-assistant.io/integrations/samsungtv/), with
some extra features.

# Installation (There are two methods, with HACS or manual)

### 1. Easy Mode

We support [HACS](https://hacs.netlify.com/). Go to "STORE", search "SamsungTV Encrypted" and install.

### 2. Manual

Install it as you would do with any homeassistant custom component:

1. Download `custom_components` folder.
2. Copy the `samsungtv_encrypted` direcotry within the `custom_components` directory of your homeassistant installation. 
The `custom_components` directory resides within your homeassistant configuration directory.
**Note**: if the custom_components directory does not exist, you need to create it.
After a correct installation, your configuration directory should look like the following.

    ```
    └── ...
    └── configuration.yaml
    └── custom_components
        └── samsungtv_encrypted
            └── __init__.py
            └── media_player.py
            └── manifest.json
            └── get_token.py
            └── PySmartCrypto
                └── pysmartcrypto.py
    ```

# Configuration

1. Use get_token.py to get your Samsung TV token (use --port 8080). Store TOKEN (CTX) and SESSION_ID output. Your TV 
must be turned on and connected to Internet with the specific IP. Terminal where you have executed get_token.py will 
ask for a PIN, that will be showed in your TV screen.  
**Note**: In some models the TOKEN can expire after a time (maybe a week, month), or even the TOKEN can be invalidated 
due to a loss of TV power. In that case you have to repeat this process again.
2. Enable the component by editing the configuration.yaml file (within the config directory as well).
Edit it by adding the following lines:
    ### Example configuration.yaml
    ```
    media_player:
      - platform: samsungtv_encrypted
        host: IP_ADDRESS
        token: TOKEN
        sessionid: SESSION_ID
        port: 8080
    ```
    **Note**: This is the same as the configuration for the built-in 
    [Samsung Smart TV](https://www.home-assistant.io/integrations/samsungtv/) component, except for the custom variables.

    ### Custom variables

    - **token:** (string) (Required) This contains the token of your encrypted TV (got in step 1)<br>

    - **sessionid:** (string) (Required) This contains the sessionid of your encrypted TV (got in step 1)<br>

    - **key_power_off:** (string) (Optional) Some TV models use an encrypted command to turn off the TV different from 
    the command that we use by default. If this is your case, try using other encrypted commands, like 'KEY_POWER' here.
    <br>Default value: 'KEY_POWEROFF'

    - **turn_on_action:** (script) (Optional) Script formatted command to turn on the TV. Example:
      ```
      - platform: samsungtv_encrypted
        ...
        turn_on_command:
          service: kodi.call_method
          data:
            entity_id: media_player.kodi
            method: Addons.ExecuteAddon
            addonid: script.json-cec
            params:
              command: turn_on 0
      ```
      <br>
    
2. Reboot Home Assistant
3. Congrats! You're all set!

# HDMI versions

H & J series TV's cannot be turned on over the network. If you have your Home Assistant server connected to the TV by
HDMI, and configured so that you can call this service to turn on the TV:
```
service: hdmi_cec.power_on
```
So, you can use the HDMI versions and getting full control over your TV.

See [HDMI-CEC integration](https://www.home-assistant.io/integrations/hdmi_cec/)

# Additional Features

### 1. Send Keys

Send keys using a native Home Assistant service:

```
service: media_player.play_media
```

```json
{
  "entity_id": "media_player.samsungtv",
  "media_content_type": "send_key",
  "media_content_id": "KEY_CODE"
}
```
**Note**: Change "KEY_CODE" by desired key_code.

You can get lots of key codes [here](https://github.com/roberodin/ha-samsungtv-custom#key-codes)

Here you can see an example of a Home Assistant script using the media_player.play_media service:
```
tv_channel_down:
  alias: Channel down
  sequence:
  - service: media_player.play_media
    data:
      entity_id: media_player.samsung_tv55
      media_content_type: "send_key"
      media_content_id: KEY_CHDOWN
```

# Working Models

- **H4500**
- **H5500**
- **H6200**
- **H6400**
- **HU7100**
- **HU7500**
- **HU8500**
- **HU8550**
- **J6350**

# Not Working Models

- **J8000**

# Contribution

Feel free to contribute with other working models and to submit fixes and improvements to the code.

If you like this custom component and it is useful for you, please consider supporting me:

<a href="https://www.buymeacoffee.com/XAF0dnBOG" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

<a href="https://www.paypal.me/sermayoral" target="_blank"><img src="https://pluspng.com/img-png/-460.png" alt="Donate with PayPal" width="170" height="36" ></a>
