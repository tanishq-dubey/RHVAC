$(document).ready(function(){
    //connect to the socket server.
    var socket = io.connect('http://' + document.domain + ':' + location.port);

	var ctx = document.getElementById("myChart");
	var color = Chart.helpers.color;
	var config = {
		type: 'line',
		data: {
			datasets: [{
				label: 'Temperature',
				borderColor: '#4183d7',
				backgroundColor: '#4183d7',
				fill: false,
				data: [],
				yAxisID: 'temp-axis',
			}, {
				label: 'Humidity',
				borderColor: '#d64541',
				backgroundColor: '#d64541',
				fill: false,
				data: [],
				yAxisID: 'humid-axis'
			}]
		},
		options: {
			responsive: true,
			title: {
				display: true,
				text: 'Temperature and Humidity'
			},
			scales: {
				xAxes: [{
					type: 'time',
					display: true,
					scaleLabel: {
						display: true,
						labelString: 'Time'
					},
					ticks: {
						major: {
							fontStyle: 'bold',
							fontColor: '#FF0000'
						}
					}
				}],
				yAxes: [{
					type: 'linear',
					display: true,
					position: 'left',
					labelString: 'Temperature',
					id: 'temp-axis',
				}, {
					type: 'linear',
					display: true,
					position: 'right',
					labelString: 'Humidity',
					id: 'humid-axis',
				}],
			}
		}
	};
	$.get('http://' + document.domain + ':' + location.port +'/data', function(data, status) {
		console.log(data);
		for(i = 0; i < data.length; i++) {
				config.data.datasets[0].data.push({
					x: data[i].time * 1000,
					y: data[i].temp
				});
				config.data.datasets[1].data.push({
					x: data[i].time * 1000,
					y: data[i].humid
				});
			}
	});
	window.myLine = new Chart(ctx, config);
	window.myLine.update();
	var lastTime = Math.round(Date.now()/1000);
	
	setInterval(function() {
		$.get('http://' + document.domain + ':' + location.port +'/data/' + lastTime, function(data, status) {
			console.log(data);
			for(i = 0; i < data.length; i++) {
				config.data.datasets[0].data.push({
					x: data[i].time * 1000,
					y: data[i].temp
				});
				config.data.datasets[1].data.push({
					x: data[i].time * 1000,
					y: data[i].humid
				});
			}
		});
		window.myLine.update();
		lastTime = Math.round(Date.now()/1000);
	}, 5000);

    //receive details from server
    socket.on('tempHeartbeat', function(msg) {
        console.log("Received temp" + msg.temp);
        $('#curr_temp').html(msg.temp);
    });

    socket.on('statusHeartbeat', function(msg) {
        console.log("Got status heartbeat");
        console.log("Enabled: " + msg.enabled);
        if (msg.enabled === true){
            $("#enabled").prop('checked', true);
        } else {
            $("#enabled").prop('checked', false);
        }

        document.getElementById("desired-temp").value = msg.desired_temperature;

        console.log("Mode: " + msg.system_mode);
        if (msg.system_mode === 'Mode.COOL') {
            $("input[name=mode_group][value=0]").prop('checked', true);
        } else if (msg.system_mode === 'Mode.HEAT') {
            $("input[name=mode_group][value=1]").prop('checked', true);
        } else if (msg.system_mode === 'Mode.AUTO') {
            $("input[name=mode_group][value=2]").prop('checked', true);
        } else {
            $("input[name=mode_group][value=3]").prop('checked', true);
        }

        console.log("State: " + msg.system_state);
        console.log("ETA: " + msg.time_to_temp);
        if (msg.system_state === 'State.IDLE') {
            $('#current_status').html("System idle at " + msg.desired_temperature + '&#8457;');

            $('#background').removeClass("light-blue amber").addClass("grey");
            $('#card-temp-color').removeClass("light-blue amber").addClass("grey");
            $('#card-ctrl-color').removeClass("light-blue amber").addClass("grey");
            $('#navbarjs').removeClass("light-blue amber").addClass("grey");

            $('#eta-text').html("");
        } else if (msg.system_state === 'State.HEATING') {
            $('#current_status').html("Heating to " + msg.desired_temperature + '&#8457;');

            $('#background').removeClass("light-blue grey").addClass("amber");
            $('#card-temp-color').removeClass("light-blue grey").addClass("amber");
            $('#card-ctrl-color').removeClass("light-blue grey").addClass("amber");
            $('#navbarjs').removeClass("light-blue grey").addClass("amber");

            $('#eta-text').html("ETA to temperature: " + msg.time_to_temp + " minutes");
        } else if (msg.system_state === 'State.COOLING') {
            $('#current_status').html("Cooling to " + msg.desired_temperature + '&#8457;');

            $('#background').removeClass("amber grey").addClass("light-blue");
            $('#card-temp-color').removeClass("amber grey").addClass("light-blue");
            $('#card-ctrl-color').removeClass("amber grey").addClass("light-blue");
            $('#navbarjs').removeClass("amber grey").addClass("light-blue");

            $('#eta-text').html("ETA to temperature: " + msg.time_to_temp + " minutes");
        } else if (msg.system_state === 'State.FAN_ONLY') {
            $('#current_status').html("Fan only mode");

            $('#background').removeClass("light-blue amber").addClass("blue-grey");
            $('#card-temp-color').removeClass("light-blue amber").addClass("blue-grey");
            $('#card-ctrl-color').removeClass("light-blue amber").addClass("blue-grey");
            $('#navbarjs').removeClass("light-blue amber").addClass("blue-grey");

            $('#eta-text').html("");
        } else if (msg.system_state === 'State.TRANSITION') {
            $('#eta-text').html("System preparing to switch modes");
        } else if (msg.system_state === 'State.DISABLED') {
            $('#current_status').html("System Off");

            $('#background').removeClass("light-blue amber").addClass("grey");
            $('#card-temp-color').removeClass("light-blue amber").addClass("grey");
            $('#card-ctrl-color').removeClass("light-blue amber").addClass("grey");
            $('#navbarjs').removeClass("light-blue amber").addClass("grey");

            $('#eta-text').html("");
        }

        $('#curr_temp').html(msg.current_temperature + '&#8457;');
    });

    $('#enabled').change(function() {
        if(this.checked) {
            socket.emit('enable_system', {data: 'disabled'});
        } else {
            socket.emit('disable_system', {data: 'enabled'});
        }
    });

    $('#desired-temp').change( function() {
        console.log(this.value);
        socket.emit('set_temperature', this.value);
    });

    $("input[name='mode_group']").change(function(e){
        if ($(this).val() == '0') {
            socket.emit('set_mode', 0);
        } else if ($(this).val() == '1') {
            socket.emit('set_mode', 1);
        } else if ($(this).val() == '2') {
            socket.emit('set_mode', 2);
        } else if ($(this).val() == '3') {
            socket.emit('set_mode', 3);
        }
    });
});
