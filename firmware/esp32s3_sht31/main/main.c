#include <stdio.h>
#include "driver/i2c.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// SHT31 I2C地址，读不到数据就改成0x45
#define SHT31_ADDR 0x44
#define I2C_SDA_GPIO 8
#define I2C_SCL_GPIO 9
#define I2C_PORT I2C_NUM_0

//I2C初始化
void i2c_init(void)
{
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_SDA_GPIO,
        .scl_io_num = I2C_SCL_GPIO,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 100000,
    };
    i2c_param_config(I2C_PORT, &conf);
    i2c_driver_install(I2C_PORT, conf.mode, 0, 0, 0);
}

//读取SHT31温湿度
esp_err_t sht31_read(float *temp, float *hum)
{
    uint8_t cmd[2] = {0x24, 0x00};
    uint8_t data[6];
    //发送测量命令
    i2c_master_write_to_device(I2C_PORT, SHT31_ADDR, cmd, 2, pdMS_TO_TICKS(100));
    vTaskDelay(pdMS_TO_TICKS(20));
    //读取6字节数据
    esp_err_t ret = i2c_master_read_from_device(I2C_PORT, SHT31_ADDR, data, 6, pdMS_TO_TICKS(100));
    if(ret != ESP_OK) return ret;

    uint16_t raw_temp = (data[0] << 8) | data[1];
    uint16_t raw_hum  = (data[3] << 8) | data[4];

    *temp = 175.0f * raw_temp / 65535.0f - 45.0f;
    *hum  = 100.0f * raw_hum / 65535.0f;
    return ESP_OK;
}

void app_main(void)
{
    i2c_init();
    float temp, hum;
    printf("SHT31 传感器启动!\n");
    while(1)
    {
        esp_err_t res = sht31_read(&temp, &hum);
        if(res == ESP_OK)
        {
            printf("温度: %.2f ℃ | 湿度: %.2f %%RH\n", temp, hum);
        }
        else
        {
            printf("读取失败！检查接线或者把地址改成0x45\n");
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
