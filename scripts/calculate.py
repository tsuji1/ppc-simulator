iddr4r = 178 * 10 ** (-3)  # read 電流(A)
vdd = 1.2  # v
cycletime = 0.5 * 10 ** (-9) # sec
power = iddr4r * vdd  # W
print("power:", power, "W")
energy = power * cycletime # J
# 1cycle 1bit であるので
energy_per_bit_pj = energy * 1  * 10**12  /8
print("1bit power:", energy_per_bit_pj, "pJ/per bit")


    
    
#     return
