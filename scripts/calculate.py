# iddr4r = 178 * 10 ** (-3)  # read 電流(A)
# vdd = 1.2  # v
# cycletime = 0.5 * 10 ** (-9) # sec
# power = iddr4r * vdd  # W
# print("power:", power, "W")
# energy = power * cycletime # J
# # 1cycle 1bit であるので
# energy_per_bit_pj = energy * 1  * 10**12  /8
# print("1bit power:", energy_per_bit_pj, "pJ/per bit")


read_burst_power = 0.5 # W 
frequency = 2 * 10 ** 9 # Hz
bl = 8
read_burst_energy= read_burst_power/ frequency / bl
read_burst_energy_pj = read_burst_energy * 10**12
print("read_burst_count:", read_burst_energy_pj)
    
#     return
# 62.5 ,31,25, 125
