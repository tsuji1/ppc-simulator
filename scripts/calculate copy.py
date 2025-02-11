# iddr4r = 178 * 10 ** (-3)  # read 電流(A)
# vdd = 1.2  # v
# cycletime = 0.5 * 10 ** (-9) # sec
# power = iddr4r * vdd  # W
# print("power:", power, "W")
# energy = power * cycletime # J
# # 1cycle 1bit であるので
# energy_per_bit_pj = energy * 1  * 10**12  /8
# print("1bit power:", energy_per_bit_pj, "pJ/per bit")


read_burst_power = 1 # W 
frequency = 2 * 10 ** 9 # Hz
read_burst_energy= read_burst_power/ frequency 
read_burst_energy_pj = read_burst_energy * 10**12
print("read_burst_count:", read_burst_energy_pj)

#     return
# 62.5 ,31,25, 125


def set_size_ppc(key_bit=13*8, capacity=1024, associative=4):
    value_bit = 15*8
    entry_size = key_bit + value_bit

    total_size_bit = entry_size * capacity
    total_size_byte = total_size_bit / 8
    blocksize = (entry_size * associative) / 8
    if total_size_byte % 1 == 0:
        total_size_byte = int(total_size_byte)
    else:
        total_size_bit = total_size_bit + 8
        total_size_byte = total_size_bit // 8
        # raise ValueError("Total size is not a whole number")
    return total_size_byte, blocksize


def set_size(key_bit, capacity, associative=4):
    value_bit = 5 * 8
    entry_size = key_bit + value_bit

    total_size_bit = entry_size * capacity
    total_size_byte = total_size_bit / 8
    blocksize = (entry_size * associative) / 8
    if total_size_byte % 1 == 0:
        total_size_byte = int(total_size_byte)
    else:
        total_size_bit = total_size_bit + 8
        total_size_byte = total_size_bit // 8
        # raise ValueError("Total size is not a whole number")
    return total_size_byte, blocksize


a,k= set_size(16,8192)
print('size',a)
