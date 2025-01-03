

def main():
    # Parse arguments
    num_packet_ip =int(input('ip4 packets num: '))
    total_time = float(input('total time: '))
    # Calculate interval
    interval = total_time / num_packet_ip
    cpu_freq = 2.0 * 10**9
    interval_cycle = interval * cpu_freq
    print('Interval(sec): ', interval)
    print('Interval(cycle):', interval_cycle)
    


        
if __name__ == '__main__':
    main()
